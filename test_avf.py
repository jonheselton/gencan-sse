import sys
import struct
import threading
import time

def synthesize_and_write(text: str, voice_id: str, speaking_rate: float):
    import AVFoundation
    import Cocoa

    synth = AVFoundation.AVSpeechSynthesizer.alloc().init()
    utt = AVFoundation.AVSpeechUtterance.speechUtteranceWithString_(text)
    utt.setRate_(speaking_rate)
    
    # Try exact identifier match first
    voice = AVFoundation.AVSpeechSynthesisVoice.voiceWithIdentifier_(voice_id)
    if not voice:
        for v in AVFoundation.AVSpeechSynthesisVoice.speechVoices():
            if v.name() == voice_id:
                voice = v
                break
    
    if voice:
        utt.setVoice_(voice)
    
    done = threading.Event()
    
    def buffer_cb(buffer):
        frames = buffer.frameLength()
        print(f"Callback! frames={frames}")
        if frames == 0:
            done.set()
            return

    t0 = time.time()
    synth.writeUtterance_toBufferCallback_(utt, buffer_cb)
    
    # Pump main run loop
    deadline = Cocoa.NSDate.dateWithTimeIntervalSinceNow_(30.0)
    while not done.is_set():
        Cocoa.NSRunLoop.currentRunLoop().runMode_beforeDate_(
            Cocoa.NSDefaultRunLoopMode,
            Cocoa.NSDate.dateWithTimeIntervalSinceNow_(0.05)
        )
        if Cocoa.NSDate.date().compare_(deadline) == Cocoa.NSOrderedDescending:
            print("Deadline reached!")
            break
            
    print(f"Done! Took {time.time() - t0:.2f} seconds.")

if __name__ == '__main__':
    synthesize_and_write("Testing dev server audio.", "Alex", 0.5)
