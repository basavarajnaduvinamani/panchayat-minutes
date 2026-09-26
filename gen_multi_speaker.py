"""Generate a multi-speaker panchayat meeting audio using different Bulbul voices."""
import httpx, base64, os, wave, io
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("SARVAM_API_KEY")

# Each speaker gets a different voice
DIALOGUE = [
    ("aditya",  "Namaste sabhi ko. Aaj ki panchayat baitak shuru karte hain. Mera naam Ramesh hai, main aapka Sarpanch hoon. Aaj teen mudde hain."),
    ("priya",   "Sarpanch ji, sabse pehle sadak ki baat karte hain. Barish mein puri sadak toot gayi hai. Bacche school nahi ja pa rahe."),
    ("aditya",  "Haan Usha ji, yeh bahut zaroori hai. Sharma Construction ne ek lakh pachaas hazar ka estimate diya hai. Kya sabhi sehmat hain?"),
    ("rahul",   "Main sehmat hoon. Lekin kaam teen mahine mein poora hona chahiye. Aur quality bhi achhi honi chahiye."),
    ("priya",   "Doosra mudda hai school ki building ki marammat. Chhat se paani tapak raha hai. Do lakh rupaye ka budget chahiye."),
    ("aditya",  "Theek hai. Suresh ji, aap yeh kaam dekhenge. 15 October tak poora karna hai. Budget manjoor kiya jaata hai."),
    ("rahul",   "Teesra agenda hai paani ki supply. Gaon mein paani bahut kam aa raha hai. Tehsildar ko patra likhna chahiye."),
    ("aditya",  "Usha ji, aap tehsildar ko patra likh dengi. Agli baitak 10 October ko hogi. Dhanyavaad sabhi ko. Baitak samaapt."),
]

all_frames = []
params = None

for i, (speaker, text) in enumerate(DIALOGUE):
    print(f"Generating line {i+1}/{len(DIALOGUE)} (speaker: {speaker})...")
    resp = httpx.post(
        "https://api.sarvam.ai/text-to-speech",
        headers={"api-subscription-key": API_KEY, "Content-Type": "application/json"},
        json={
            "inputs": [text],
            "target_language_code": "hi-IN",
            "speaker": speaker,
            "model": "bulbul:v3",
            "enable_preprocessing": True,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Error: {resp.text}")
        exit(1)

    wav_bytes = base64.b64decode(resp.json()["audios"][0])
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        if params is None:
            params = wf.getparams()
        all_frames.append(wf.readframes(wf.getnframes()))
        # Add 0.5s silence between speakers
        silence = b'\x00' * int(wf.getframerate() * wf.getsampwidth() * wf.getnchannels() * 0.4)
        all_frames.append(silence)

out_path = "test_multi_speaker.wav"
with wave.open(out_path, "wb") as out:
    out.setparams(params)
    for frames in all_frames:
        out.writeframes(frames)

size_kb = os.path.getsize(out_path) // 1024
print(f"Saved: {out_path} ({size_kb} KB)")
print(f"Upload this to http://localhost:8000 for the multi-speaker demo!")
