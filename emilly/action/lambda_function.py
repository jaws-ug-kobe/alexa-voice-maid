# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import stat
import subprocess
import boto3
import logging
import json
import shutil
from boto3 import Session
from boto3 import resource
from boto3.dynamodb.conditions import Key, Attr
from contextlib import closing
import s3_glue

session = Session(region_name="us-east-1")
polly = session.client("polly")
dynamodb = boto3.resource('dynamodb')

TTS_FILE = "/tmp/tts.mp3"
CONVERTED_TTS_FILE = "/tmp/converted_tts.mp3"

LAMBDA_TMP_DIR = "/tmp"
LAMBDA_BASE_DIR = "/var/task"
FFMPEG_BIN = "{0}/ffmpeg".format(LAMBDA_TMP_DIR)
FFMPEG_CONVERT_COMAND = "{} -y -i {} -ac 2 -codec:a libmp3lame -b:a 48k -ar 16000 {} -nostdin"
shutil.copyfile("{}/ffmpeg.linux64".format(LAMBDA_BASE_DIR), FFMPEG_BIN)
os.environ['IMAGEIO_FFMPEG_EXE'] = FFMPEG_BIN
os.chmod(FFMPEG_BIN, os.stat(FFMPEG_BIN).st_mode | stat.S_IEXEC)


# --------------- Helpers that build all of the responses ----------------------

def build_speechlet_response(title, output, reprompt_text, should_end_session):
    return {
        'outputSpeech': {
            'type': 'PlainText',
            'text': output
        },
        'card': {
            'type': 'Simple',
            'title': "SessionSpeechlet - " + title,
            'content': "SessionSpeechlet - " + output
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'PlainText',
                'text': reprompt_text
            }
        },
        'shouldEndSession': should_end_session
    }

# SSML形式の戻り値JSONを生成
def build_audio_response(title, output, audio_url, should_end_session):
    return {
        'outputSpeech': {
            'type': 'SSML',
            'ssml': '<speak><audio src="https://s3.amazonaws.com/voice.maid.audio/converted_tts.mp3" /></speak>'
        },
        'card': {
            'type': 'Simple',
            'title': 'SessionSpeechlet - ' + title,
            'content': 'SessionSpeechlet - ' + output
        },
        'reprompt': {
            'outputSpeech': {
                'type': 'SSML',
                'ssml': '<speak><audio src="https://s3.amazonaws.com/voice.maid.audio/converted_tts.mp3" /></speak>'
            }
        },
        'shouldEndSession': should_end_session
    }


def build_response(session_attributes, speechlet_response):
    return {
        'version': '1.0',
        'sessionAttributes': session_attributes,
        'response': speechlet_response
    }

# --------------- Functions that acquire secual user control ------------------
def get_user():
    table = dynamodb.Table('maid_status')
    user = table.query(
        KeyConditionExpression=Key('maid_name').eq("tomoharu"))
    return user[u'Items'][0]


def set_user_state(state=None):
    table = dynamodb.Table('maid_status')
    table.update_item(
        Key={'maid_name': "tomoharu"},
        UpdateExpression="set maid_state = :val",
        ExpressionAttributeValues={':val': state},
        ReturnValues="UPDATED_NEW"
    )


def text_to_speech(text=""):
    print("text: %s" % text)
    response = polly.synthesize_speech(
        Text=text,
        OutputFormat="mp3",
        SampleRate="16000",
        VoiceId="Mizuki")
    with closing(response["AudioStream"]) as stream:
        with open(TTS_FILE, "wb") as f:
            f.write(stream.read())
    return fit_to_alexa()

def fit_to_alexa():
    cmd = FFMPEG_CONVERT_COMAND.format(FFMPEG_BIN, TTS_FILE, CONVERTED_TTS_FILE)
    ret_code = subprocess.call(cmd, shell=True)
    if ret_code != 0:
        print("convert faild!:{}".format(ret_code))
        return False

    s3 = s3_glue.get_s3()
    s3.Object("voice.maid.audio", "converted_tts.mp3").upload_file(CONVERTED_TTS_FILE)
    s3.ObjectAcl("voice.maid.audio", "converted_tts.mp3").put(ACL="public-read")
    return True

# --------------- Functions that control the skill's behavior ------------------

def get_welcome_response(user_from_alexa=None):
    """ If we wanted to initialize the session to have some attributes we could
    add those here
    """

    session_attributes = {}
    card_title = "Welcome alexa maid."
    user = get_user()
    if user[u'maid_state'] == 1: # user is in his home.
        # speech_output = "Master, Ga issue too desuka?"
        speech_output = "ご主人様、外出なさいますか？"
        reprompt_text = ""
        session_attributes = {"user_state": "going_out"}
    else: # user is out of his home.
        # speech_output = "Okaerinasai ma se, Master. o huroni shimasuka? soretomo gohann ni shimasuka?"
        speech_output = "お帰りなさいませ、ご主人様。お食事になさいますか? それとも、お風呂になさいますか?"
        reprompt_text = ""
        session_attributes = {"user_state": "came_back"}

    if text_to_speech(speech_output) == True:
        should_end_session = False
    else:
        should_end_session = True
    # return build_response(session_attributes, build_speechlet_response(
    #     card_title, speech_output, reprompt_text, should_end_session))
    return build_response(session_attributes, build_audio_response(
        card_title, speech_output, CONVERTED_TTS_FILE, should_end_session))


def handle_session_end_request():
    card_title = "Session Ended"
    speech_output = "お休みなさいませ。ご主人様。"

    text_to_speech(speech_output)
    # Setting this to true ends the session and exits the skill.
    should_end_session = True
    return build_response(session_attributes, build_audio_response(
        card_title, speech_output, CONVERTED_TTS_FILE, should_end_session))
    # return build_response({}, build_speechlet_response(
    #     card_title, speech_output, None, should_end_session))



def where_you_go(intent, session):

    card_title = intent['name']
    session_attributes = session.get('attributes',{})
    should_end_session = True

    if 'destination' in intent['slots']:
        destination = intent['slots']['destination']['value']

        set_user_state(2)
        speech_output = destination + " ですね! いってらっしゃいませ。"
        reprompt_text = "もう一度お願いします。"
    else:
        speech_output = "もう一度お願いします。"
        reprompt_text = "もう一度お願いします。"

    text_to_speech(speech_output)

    # return build_response(session_attributes, build_speechlet_response(
    #     card_title, speech_output, reprompt_text, should_end_session))
    return build_response(session_attributes, build_audio_response(
        card_title, speech_output, CONVERTED_TTS_FILE, should_end_session))


def take_bath(intent, session):

    card_title = intent['name']
    session_attributes = session.get('attributes', {})
    should_end_session = True

    speech_output = "お風呂ですね。ごゆっくりお体をおやすませください。"
    reprompt_text = "もう一度お願いします。"
    set_user_state(1)

    text_to_speech(speech_output)

    # Setting reprompt_text to None signifies that we do not want to reprompt
    # the user. If the user does not respond or says something that is not
    # understood, the session will end.
    # return build_response(session_attributes, build_speechlet_response(
    #     intent['name'], speech_output, reprompt_text, should_end_session))
    return build_response(session_attributes, build_audio_response(
        card_title, speech_output, CONVERTED_TTS_FILE, should_end_session))


def have_meals(intent, session):
    card_title = intent['name']
    session_attributes = session.get('attributes', {})
    should_end_session = True

    speech_output = "お食事ですね。ご用意できております。"
    reprompt_text = "もう一度お願いします。"
    set_user_state(1)

    text_to_speech(speech_output)

    # Setting reprompt_text to None signifies that we do not want to reprompt
    # the user. If the user does not respond or says something that is not
    # understood, the session will end.
    return build_response(session_attributes, build_audio_response(
        card_title, speech_output, CONVERTED_TTS_FILE, should_end_session))
    # return build_response(session_attributes, build_speechlet_response(
    #     intent['name'], speech_output, reprompt_text, should_end_session))


# --------------- Events ------------------

def on_session_started(session_started_request, session):
    """ Called when the session starts """

    print("on_session_started requestId=" + session_started_request['requestId']
          + ", sessionId=" + session['sessionId'])


def on_launch(launch_request, session):
    """ Called when the user launches the skill without specifying what they
    want
    """

    print("on_launch requestId=" + launch_request['requestId'] +
          ", sessionId=" + session['sessionId'])
    # Dispatch to your skill's launch
    return get_welcome_response(session[u'user'])


def on_intent(intent_request, session):
    """ Called when the user specifies an intent for this skill """

    print("on_intent requestId=" + intent_request['requestId'] +
          ", sessionId=" + session['sessionId'])

    intent = intent_request['intent']
    intent_name = intent_request['intent']['name']
    print(intent_name)

    # Dispatch to your skill's intent handlers
    if intent_name == "WhereYouGoIntent":
        return where_you_go(intent, session)
    elif intent_name == "TakeBathIntent":
        return take_bath(intent, session)
    elif intent_name == "HaveMealIntent":
        return have_meals(intent, session)
    elif intent_name == "AMAZON.HelpIntent":
        return get_welcome_response(session[u'user'])
    elif intent_name == "AMAZON.CancelIntent" or intent_name == "AMAZON.StopIntent":
        return handle_session_end_request()
    else:
        raise ValueError("Invalid intent")


def on_session_ended(session_ended_request, session):
    """ Called when the user ends the session.

    Is not called when the skill returns should_end_session=true
    """
    print("on_session_ended requestId=" + session_ended_request['requestId'] +
          ", sessionId=" + session['sessionId'])
    # add cleanup logic here


# --------------- Main handler ------------------

def lambda_handler(event, context):
    """ Route the incoming request based on type (LaunchRequest, IntentRequest,
    etc.) The JSON body of the request is provided in the event parameter.
    """
    print("event.session.application.applicationId=" +
          event['session']['application']['applicationId'])

    """
    Uncomment this if statement and populate with your skill's application ID to
    prevent someone else from configuring a skill that sends requests to this
    function.
    """
    # if (event['session']['application']['applicationId'] !=
    #         "amzn1.echo-sdk-ams.app.[unique-value-here]"):
    #     raise ValueError("Invalid Application ID")

    print(event)
    print(context)
    if event['session']['new']:
        on_session_started({'requestId': event['request']['requestId']},
                           event['session'])

    if event['request']['type'] == "LaunchRequest":
        return on_launch(event['request'], event['session'])
    elif event['request']['type'] == "IntentRequest":
        return on_intent(event['request'], event['session'])
    elif event['request']['type'] == "SessionEndedRequest":
        return on_session_ended(event['request'], event['session'])
