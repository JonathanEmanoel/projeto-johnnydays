import re
import os
import time
from datetime import datetime, timedelta
from django.utils.timezone import make_aware
from django.http import HttpResponse
from rest_framework import viewsets
from twilio.twiml.messaging_response import MessagingResponse
from django.views.decorators.csrf import csrf_exempt
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from twilio.rest import Client as TwilioClient
from jonnysdays_chatbot import settings
from django.utils.timezone import make_aware, get_current_timezone
import logging

from .models import Client, Locutor, Studio, Booking
from .serializers import ClientSerializer, LocutorSerializer, StudioSerializer, BookingSerializer

# Configurar o cliente Twilio
twilio_client = TwilioClient(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)

logger = logging.getLogger(__name__)

# Configuração da API do Google Calendar
SCOPES = ['https://www.googleapis.com/auth/calendar']

# Variável global para rastrear o estado da conversa
client_context = {}

# Configuração do Google Calendar
def get_google_calendar_service():
    creds = None
    token_path = 'token.json'
    creds_path = 'client_secret_690118972975-lev3607fp3k6gjqosrpi9dgku1gquj7c.apps.googleusercontent.com.json'
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=9000)
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

def create_google_calendar_event(booking):
    service = get_google_calendar_service()
    
    attendees = []
    if booking.locutor.email:
        attendees.append({'email': booking.locutor.email})
    if booking.client.email:
        attendees.append({'email': booking.client.email})

    logger.info(f"Attendees: {attendees}")

    event = {
        'summary': f'Gravação no estúdio da JonnysDays com {booking.locutor.name}',
        'location': booking.studio.location,
        'description': f'Sessão de gravação no estúdio {booking.studio.name}.',
        'start': {
            'dateTime': booking.start_time.isoformat(),
            'timeZone': 'America/Sao_Paulo',
        },
        'end': {
            'dateTime': booking.end_time.isoformat(),
            'timeZone': 'America/Sao_Paulo',
        },
        'attendees': attendees,
        'reminders': {
            'useDefault': False,
            'overrides': [
                {'method': 'email', 'minutes': 24 * 60},
                {'method': 'popup', 'minutes': 10},
            ],
        },
    }

    logger.info(f"Creating event: {event}")
    service.events().insert(calendarId='primary', body=event).execute()




# Verifica disponibilidade no banco de dados
def is_studio_available_in_db(studio_name, date, time, duration):
    studio = Studio.objects.get(name=studio_name)
    start_time = make_aware(datetime.combine(date, time))
    end_time = start_time + timedelta(hours=duration)
    bookings = Booking.objects.filter(studio=studio, start_time__lt=end_time, end_time__gt=start_time)
    return not bookings.exists()

# Extrai horário da mensagem
def extract_time_from_message(message):
    match = re.search(r'\b([01]?[0-9]|2[0-3])h\b', message)
    if match:
        time_str = match.group(0).replace("h", ":00")
        return datetime.strptime(time_str, '%H:%M').time()
    return None

# Extrai data da mensagem
def extract_date_from_message(message):
    match = re.search(r'\b(\d{2}/\d{2}/\d{4})\b', message)
    if match:
        return datetime.strptime(match.group(0), '%d/%m/%Y').date()
    return None



def create_booking(client, locutor_name, studio_name, start_date, start_time, duration):
    studio = Studio.objects.get(name=studio_name)
    locutor = Locutor.objects.get(name=locutor_name)

    timezone = get_current_timezone()
    start_time_aware = make_aware(datetime.combine(start_date, start_time), timezone)
    end_time_aware = start_time_aware + timedelta(hours=duration)

    logger.info(f"Criando booking: start_time={start_time_aware}, end_time={end_time_aware}")

    booking = Booking.objects.create(
        client=client,
        locutor=locutor,
        studio=studio,
        start_time=start_time_aware,
        end_time=end_time_aware
    )

    logger.info("Enviando evento ao Google Calendar...")
    create_google_calendar_event(booking)
    return booking

def send_message_to_client(client, message):
    """Envia mensagem para o cliente via Twilio"""
    from_number = settings.TWILIO_WHATSAPP_SANDBOX_NUMBER
    to_number = f"whatsapp:{client.phone}"

    try:
        twilio_client.messages.create(
            body=message,
            from_=from_number,
            to=to_number
        )
        print(f"Mensagem enviada para o cliente {client.name}: {message}")
        return True
    except Exception as e:
        print(f"Erro ao enviar mensagem para o cliente {client.name}: {e}")
        return False


def send_message_to_locutor(locutor, message):
    """Envia mensagem para o locutor via Twilio"""
    try:
        twilio_client.messages.create(
            body=message,
            from_="whatsapp:+14155238886",
            to=f"whatsapp:{locutor.phone}"
        )
        print(f"Mensagem enviada para o locutor {locutor.name}: {message}")
        return True
    except Exception as e:
        print(f"Erro ao enviar mensagem para o locutor {locutor.name}: {e}")
        return False



def extract_duration_from_message(message):
    """
    Extrai a duração em horas da mensagem enviada pelo cliente.
    """
    match = re.search(r'\b(\d+)\s*(h|hora|horas)\b', message, re.IGNORECASE)
    if match:
        return int(match.group(1))  # Retorna a duração como um inteiro
    return None  # Retorna None se não encontrar uma duração válida

def suggest_alternative_times(date, studio_name, duration):
    studio = Studio.objects.get(name=studio_name)
    existing_bookings = Booking.objects.filter(studio=studio, start_time__date=date)

    # Sugira horários diferentes com base em intervalos
    suggestions = []
    start_of_day = make_aware(datetime.combine(date, datetime.min.time()))
    end_of_day = make_aware(datetime.combine(date, datetime.max.time()))
    interval = timedelta(hours=1)

    current_time = start_of_day
    while current_time + timedelta(hours=duration) <= end_of_day:
        if not existing_bookings.filter(start_time__lt=current_time + timedelta(hours=duration), end_time__gt=current_time).exists():
            suggestions.append(current_time.strftime('%H:%M'))
        current_time += interval

    return suggestions[:3]  # Retorne até 3 sugestões


@csrf_exempt
def whatsapp_webhook(request):
    incoming_msg = request.POST.get('Body', '').strip()
    phone_number = request.POST.get('From', '').replace('whatsapp:', '')

    # Inicializa uma mensagem padrão para evitar erros
    response_msg = "Desculpe, ocorreu um erro inesperado. Por favor, tente novamente."

    try:
        # Verifica se é uma resposta do locutor
        if f"locutor_{phone_number}" in client_context:
            locutor_context = client_context[f"locutor_{phone_number}"]
            client_phone = locutor_context["client_phone"]
            client = locutor_context["client"]
            date = locutor_context["date"]
            time = locutor_context["time"]
            duration = locutor_context["duration"]
            studio = locutor_context["studio"]
            attempts = locutor_context.get("attempts", 0)
            locutor = Locutor.objects.get(phone=phone_number)

            locutor_response = incoming_msg.lower()

            if locutor_response in ["sim", "confirmo"]:
                # Locutor confirmou o horário
                booking = create_booking(client, locutor.name, studio, date, time, duration)
                formatted_date = booking.start_time.strftime('%d/%m/%Y')
                formatted_time = booking.start_time.strftime('%H:%M')
                response_msg = (
                    f"Agendamento confirmado! Locutor {locutor.name} confirmou para o dia {formatted_date} às {formatted_time} com duração de {duration}h."
                )
                send_message_to_client(
                    client,
                    f"O locutor {locutor.name} confirmou sua gravação para {formatted_date} às {formatted_time} com duração de {duration}h.",
                )
                del client_context[f"locutor_{phone_number}"]
            elif locutor_response in ["não", "nao"]:
                if attempts < 2:
                    locutor_context["attempts"] += 1
                    response_msg = "Entendido. Você tem outro horário disponível no dia {date}? Por favor, envie o horário no formato HHh."
                    locutor_context["state"] = "awaiting_new_time"
                else:
                    response_msg = "Já que não houve acordo de horário entre as partes, um dos nossos especialistas irá entrar em contato para poder finalizar o agendamento! A JonnysDays agradece e já retornaremos com o nosso agendamento."
                    send_message_to_client(client, response_msg)
                    del client_context[f"locutor_{phone_number}"]
            elif locutor_context.get("state") == "awaiting_new_time":
                new_time = extract_time_from_message(incoming_msg)
                if new_time:
                    locutor_context["time"] = new_time
                    client_context[client_phone]["selected_time"] = new_time
                    response_msg = f"Novo horário {new_time} recebido. Consultando o cliente sobre a disponibilidade."
                    send_message_to_client(client, f"O locutor sugeriu o horário {new_time} no dia {date}. Está bom para você?")
                    client_context[client_phone]["state"] = "awaiting_client_confirmation"
                else:
                    response_msg = "Por favor, envie o horário no formato HHh."
            else:
                response_msg = "Desculpe, não entendi. Por favor, envie 'Sim' ou 'Não'."

        else:
            # Cliente: Verifica ou cria o cliente no banco de dados
            client, created = Client.objects.get_or_create(phone=phone_number)

            if created:
                response_msg = "Olá! Somos da JonnysDays, e é um prazer atendê-lo(a). Por favor, me diga seu nome."
                client_context[phone_number] = "awaiting_name"
            else:
                state = client_context.get(phone_number, None)

                if not state:
                    response_msg = (
                        f"Olá, {client.name}! A JonnysDays agradece o seu contato. Qual horário você deseja fazer o agendamento? "
                        "Envie no formato DD/MM/AAAA e HHh."
                    )
                    client_context[phone_number] = "awaiting_datetime"
                elif state == "awaiting_name":
                    client.name = incoming_msg
                    client.save()
                    response_msg = f"Obrigado, {client.name}! Agora, por favor, me diga o nome da sua empresa."
                    client_context[phone_number] = "awaiting_company"
                elif state == "awaiting_company":
                    client.company = incoming_msg
                    client.save()
                    response_msg = "Obrigado! Agora, por favor, me informe seu e-mail."
                    client_context[phone_number] = "awaiting_email"
                elif state == "awaiting_email":
                    client.email = incoming_msg
                    client.save()
                    response_msg = (
                        "Cadastro concluído! Qual data e horário você gostaria de agendar a gravação? "
                        "Envie no formato DD/MM/AAAA e HHh."
                    )
                    client_context[phone_number] = "awaiting_datetime"
                elif state == "awaiting_datetime":
                    preferred_date = extract_date_from_message(incoming_msg)
                    preferred_time = extract_time_from_message(incoming_msg)

                    if preferred_date and preferred_time:
                        client_context[phone_number] = {
                            "state": "awaiting_duration",
                            "selected_date": preferred_date,
                            "selected_time": preferred_time,
                        }
                        response_msg = "Obrigado! Agora, informe a duração da gravação em horas (ex: 2h)."
                    else:
                        response_msg = "Por favor, envie a data e horário no formato correto (ex: 10/12/2024 14h)."
                elif isinstance(client_context[phone_number], dict) and client_context[phone_number].get("state") == "awaiting_duration":
                    duration = extract_duration_from_message(incoming_msg)

                    if duration:
                        client_context[phone_number]["duration"] = duration
                        response_msg = (
                            f"O estúdio está disponível no horário {client_context[phone_number]['selected_time']} "
                            f"para {duration}h de gravação. Qual locutor você prefere?"
                        )
                        client_context[phone_number]["state"] = "awaiting_locutor"
                    else:
                        response_msg = "Por favor, envie a duração no formato correto (ex: 2h)."
                elif isinstance(client_context[phone_number], dict) and client_context[phone_number].get("state") == "awaiting_locutor":
                    locutor_name = incoming_msg
                    try:
                        locutor = Locutor.objects.get(name__iexact=locutor_name)

                        selected_date = client_context[phone_number]["selected_date"]
                        selected_time = client_context[phone_number]["selected_time"]
                        duration = client_context[phone_number]["duration"]

                        formatted_date = selected_date.strftime('%d/%m/%Y')
                        formatted_time = selected_time.strftime('%H:%M')
                        message = (
                            f"Olá {locutor.name}, o cliente {client.name} gostaria de gravar no dia "
                            f"{formatted_date} às {formatted_time} com duração de {duration}h. Você confirma?"
                        )
                        if send_message_to_locutor(locutor, message):
                            response_msg = "Estamos aguardando a confirmação do locutor."
                            client_context[f"locutor_{locutor.phone}"] = {
                                "client_phone": phone_number,
                                "client": client,
                                "date": selected_date,
                                "time": selected_time,
                                "duration": duration,
                                "studio": "JonnysDaysS1",
                                "attempts": 0,
                            }
                            client_context[phone_number]["state"] = "awaiting_locutor_confirmation"
                        else:
                            response_msg = "Erro ao enviar mensagem ao locutor. Tente novamente."
                    except Locutor.DoesNotExist:
                        response_msg = "Desculpe, não encontramos o locutor informado. Por favor, tente novamente."
                elif state == "awaiting_client_confirmation":
                    if incoming_msg.lower() in ["sim", "confirmo"]:
                        locutor_context = client_context[f"locutor_{phone_number}"]
                        locutor_context["attempts"] = 0
                        response_msg = "Horário aceito! Confirmando com o locutor."
                        send_message_to_locutor(locutor, f"O cliente aceitou o horário {locutor_context['time']} no dia {locutor_context['date']}. Está bom para você?")
                        locutor_context["state"] = "awaiting_locutor_confirmation"
                    else:
                        available_times = suggest_alternative_times(
                            client_context[phone_number]["selected_date"],
                            "JonnysDaysS1",
                            client_context[phone_number]["duration"]
                        )
                        if available_times:
                            response_msg = f"Horários alternativos: {', '.join(available_times)}. Algum desses horários serve para você?"
                        else:
                            response_msg = "Desculpe, não encontramos horários disponíveis. Por favor, sugira um novo horário."

    except Exception as e:
        # Log do erro e mensagem genérica para o cliente
        print(f"Erro no webhook: {e}")
        response_msg = f"Erro no processamento: {e}. Por favor, tente novamente."

    # Envia a resposta para o WhatsApp
    resp = MessagingResponse()
    resp.message(response_msg)
    return HttpResponse(str(resp), content_type="text/xml")

# Viewsets
class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.all()
    serializer_class = ClientSerializer

class LocutorViewSet(viewsets.ModelViewSet):
    queryset = Locutor.objects.all()
    serializer_class = LocutorSerializer

class StudioViewSet(viewsets.ModelViewSet):
    queryset = Studio.objects.all()
    serializer_class = StudioSerializer

class BookingViewSet(viewsets.ModelViewSet):
    queryset = Booking.objects.all()
    serializer_class = BookingSerializer
