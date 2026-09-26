"""Generate a sample panchayat meeting audio using Sarvam Bulbul TTS."""
import httpx, base64, os, wave, io
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("SARVAM_API_KEY")

PARTS = [
    "Aaj ki gram panchayat baitak mein Sarpanch Ramesh Kumar ji, Usha Devi ji, Mohan Lal ji, aur paanch anya sadasy maujood the. Baitak ka pehla agenda tha gaon mein nayi sadak ka nirman. Sabhi sadasy ne sehmat hokar Sharma Construction ko kaam dene ka nirnay liya. Kaam teen mahine mein poora karna hai.",
    "Budget ek lakh pachaas hazar rupaye hai. Doosra mudda tha sarkaari school ki marammat. Do lakh rupaye ka budget pass kiya gaya. Suresh ji ko zimmedaar banaya gaya, kaam 15 October tak hona chahiye. Teesra agenda pani supply badhana tha. Tehsildar ko patra likhenge Usha Devi ji. Agli baitak 10 October ko hogi."
]

all_frames = []
params = None

for i, part in enumerate(PARTS):
    print(f"Generating part {i+1}/{len(PARTS)}...")
    resp = httpx.post(
        "https://api.sarvam.ai/text-to-speech",
        headers={"api-subscription-key": API_KEY, "Content-Type": "application/json"},
        json={
            "inputs": [part],
            "target_language_code": "hi-IN",
            "speaker": "ritu",
            "model": "bulbul:v3",
            "enable_preprocessing": True,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"Error on part {i+1}:", resp.text)
        exit(1)

    wav_bytes = base64.b64decode(resp.json()["audios"][0])
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        if params is None:
            params = wf.getparams()
        all_frames.append(wf.readframes(wf.getnframes()))

out_path = "test_panchayat_meeting.wav"
with wave.open(out_path, "wb") as out:
    out.setparams(params)
    for frames in all_frames:
        out.writeframes(frames)

size_kb = os.path.getsize(out_path) // 1024
print(f"✅ Saved: {out_path} ({size_kb} KB)")
print("🎉 Upload this file to http://localhost:8000 to demo!")
