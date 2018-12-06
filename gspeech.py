# -*- coding: utf-8 -*-
from __future__ import division

import re
import sys

from google.cloud import speech
from google.cloud.speech import enums
from google.cloud.speech import types
import pyaudio
from six.moves import queue
from threading import Thread
import time

import wave
from google.cloud import texttospeech

import os

# 각자 발급 받은 json File을 넣으면 됩니다.
os.environ["GOOGLE_APPLICATION_CREDENTIALS"]='file_name.json'

# Audio recording parameters
RATE = 16000
CHUNK = int(RATE / 10)  # 100ms

class MicrophoneStream(object):
    """Opens a recording stream as a generator yielding the audio chunks."""
    def __init__(self, rate, chunk):
        self._rate = rate
        self._chunk = chunk

        # Create a thread-safe buffer of audio data
        self._buff = queue.Queue()
        self.closed = True
        self.isPause = False

    def __enter__(self):
        self._audio_interface = pyaudio.PyAudio()
        self._audio_stream = self._audio_interface.open(
            format=pyaudio.paInt16,
            channels=1, rate=self._rate,
            input=True, frames_per_buffer=self._chunk,
            stream_callback=self._fill_buffer,
        )

        self.closed = False

        return self

    def __exit__(self, type, value, traceback):
        self._audio_stream.stop_stream()
        self._audio_stream.close()


        self.closed = True
        self._buff.put(None)
        self._audio_interface.terminate()

    def pause(self):
        if self.isPause == False:
            self.isPause = True


    def resume(self):
        if self.isPause == True:
            self.isPause = False


    def status(self):
        return self.isPause

    def _fill_buffer(self, in_data, frame_count, time_info, status_flags):
        """Continuously collect data from the audio stream, into the buffer."""
        if self.isPause == False:
            self._buff.put(in_data)
        #else
        return None, pyaudio.paContinue

    def generator(self):
        while not self.closed:
            chunk = self._buff.get()
            if chunk is None:
                return

            data = [chunk]

            while True:
                try:
                    chunk = self._buff.get(block=False)
                    if chunk is None:
                        return
                    data.append(chunk)
                except queue.Empty:
                    break

            yield b''.join(data)


# [END audio_stream]

class Gspeech(Thread):
    def __init__(self):
        Thread.__init__(self)

        self.language_code = 'ko-KR'  # a BCP-47 language tag

        self._buff = queue.Queue()

        self.client = speech.SpeechClient()
        self.config = types.RecognitionConfig(
            encoding=enums.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=RATE,
            language_code=self.language_code)
        self.streaming_config = types.StreamingRecognitionConfig(
            config=self.config,
            interim_results=True)

        self.mic = None
        self.status = True

        self.daemon = True
        self.start()

    def __eixt__(self):
        self._buff.put(None)

    def run(self):
        with MicrophoneStream(RATE, CHUNK) as stream:
            self.mic = stream
            audio_generator = stream.generator()
            requests = (types.StreamingRecognizeRequest(audio_content=content)
                        for content in audio_generator)

            responses = self.client.streaming_recognize(self.streaming_config, requests)

            # Now, put the transcription responses to use.
            self.listen_print_loop(responses, stream)
        self._buff.put(None)
        self.status = False

    def pauseMic(self):
        if self.mic is not None:
            self.mic.pause()

    def resumeMic(self):
        if self.mic is not None:
            self.mic.resume()

    # 인식된 Text 가져가기
    def getText(self, block = True):
        return self._buff.get(block=block)

    # TTS
    def text_to_speech(self, text):
        client = texttospeech.TextToSpeechClient()

        # Set the text input to be synthesized
        synthesis_input = texttospeech.types.SynthesisInput(text=text)

        # Build the voice request, select the language code ("ko-KR") and the ssml
        # voice gender ("neutral")
        voice = texttospeech.types.VoiceSelectionParams(
            language_code='ko-KR',
            ssml_gender=texttospeech.enums.SsmlVoiceGender.NEUTRAL)

        # Select the type of audio file you want returned
        audio_config = texttospeech.types.AudioConfig(
            audio_encoding=texttospeech.enums.AudioEncoding.LINEAR16)

        # Perform the text-to-speech request on the text input with the selected
        # voice parameters and audio file type
        response = client.synthesize_speech(synthesis_input, voice, audio_config)

        # The response's audio_content is binary.
        with open('tmp.wav', 'wb') as out:
            # Write the response to the output file.
            out.write(response.audio_content)

        tmpPlayPath = 'tmp.wav'

        wf = wave.open(tmpPlayPath, 'rb')
        p = pyaudio.PyAudio()
        chunk = 1024

        # open stream based on the wave object which has been input.
        stream = p.open(format=p.get_format_from_width(wf.getsampwidth()),
                        channels=wf.getnchannels(),
                        rate=wf.getframerate(),
                        output=True)

        # read data (based on the chunk size)
        data = wf.readframes(chunk)

        # play stream (looping from beginning of file to the end)
        while data != '':
            # writing to the stream is what *actually* plays the sound.
            stream.write(data)
            data = wf.readframes(chunk)
            if len(data) == 0:
               break

        # cleanup stuff.
        stream.stop_stream()
        stream.close()
        p.terminate()


    # 음성인식 처리 루틴
    def listen_print_loop(self, responses, mic):
        num_chars_printed = 0
        try:
            for response in responses:
                if not response.results:
                    continue

                result = response.results[0]
                if not result.alternatives:
                    continue

                transcript = result.alternatives[0].transcript
                overwrite_chars = ' ' * (num_chars_printed - len(transcript))
                if not result.is_final:
                    sys.stdout.write(transcript + overwrite_chars + '\r')
                    sys.stdout.flush()
                    #### 추가 ### 화면에 인식 되는 동안 표시되는 부분.
                    num_chars_printed = len(transcript)
                else:
                    # 큐에 넣는다.
                    self._buff.put(transcript+overwrite_chars)
                    num_chars_printed = 0
        except:
            return