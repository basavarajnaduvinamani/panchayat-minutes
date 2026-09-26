import os
import json
import base64
import wave
import httpx
import tempfile
from io import BytesIO
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# PDF
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

load_dotenv()

SARVAM_API_KEY = os.getenv("SARVAM_API_KEY", "")
SARVAM_BASE = "https://api.sarvam.ai"

app = FastAPI(title="Panchayat Minutes Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Serve frontend ───────────────────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="."), name="static")


@app.get("/")
async def root():
    return FileResponse("index.html")


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "api_key_set": bool(SARVAM_API_KEY)}


# ─── Step 1: Saaras STT (with auto-chunking for >30s audio) ───────────────────
def split_wav_chunks(audio_bytes: bytes, chunk_seconds: int = 25) -> list[bytes]:
    """Split WAV audio into chunks of chunk_seconds each."""
    try:
        with wave.open(BytesIO(audio_bytes)) as wf:
            params = wf.getparams()
            framerate = wf.getframerate()
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            total_frames = wf.getnframes()
            frames_per_chunk = framerate * chunk_seconds
            chunks = []
            while wf.tell() < total_frames:
                frames_to_read = min(frames_per_chunk, total_frames - wf.tell())
                raw = wf.readframes(frames_to_read)
                buf = BytesIO()
                with wave.open(buf, "wb") as out:
                    out.setnchannels(n_channels)
                    out.setsampwidth(sampwidth)
                    out.setframerate(framerate)
                    out.writeframes(raw)
                chunks.append(buf.getvalue())
            return chunks
    except Exception:
        # Not a valid WAV — return as-is (let the API handle it)
        return [audio_bytes]


async def transcribe_chunk(audio_bytes: bytes, filename: str) -> str:
    """Transcribe a single audio chunk via Saaras."""
    headers = {"api-subscription-key": SARVAM_API_KEY}
    async with httpx.AsyncClient(timeout=60) as client:
        files = {"file": (filename, audio_bytes, "audio/wav")}
        data = {
            "model": "saaras:v4-multispk",
            "language_code": "hi-IN",
            "with_timestamps": False,
        }
        resp = await client.post(
            f"{SARVAM_BASE}/speech-to-text",
            headers=headers,
            files=files,
            data=data,
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Saaras STT error: {resp.text}")
    result = resp.json()
    # Multispeaker returns transcript with speaker labels
    return result.get("transcript", "")


async def transcribe_audio(audio_bytes: bytes, filename: str) -> dict:
    """Transcribe audio, auto-chunking if longer than 30s."""
    chunks = split_wav_chunks(audio_bytes, chunk_seconds=25)
    transcripts = []
    for i, chunk in enumerate(chunks):
        chunk_name = f"chunk_{i}.wav"
        text = await transcribe_chunk(chunk, chunk_name)
        if text.strip():
            transcripts.append(text.strip())
    transcript = " ".join(transcripts)
    return {"transcript": transcript}


# ─── Step 2: Sarvam-105B Extract Minutes ─────────────────────────────────────
EXTRACTION_PROMPT = """You are an expert panchayat secretary. Given a raw meeting transcript (may be in Hindi, mixed Hindi-English, or regional language), extract the following in strict JSON:

{
  "meeting_title": "short title of the meeting",
  "date_mentioned": "any date found or 'Not specified'",
  "attendees": ["list of names/roles mentioned"],
  "agenda_items": ["list of topics discussed"],
  "decisions": [
    {"decision": "what was decided", "details": "context"}
  ],
  "action_items": [
    {"action": "what needs to be done", "responsible": "who", "deadline": "when or TBD"}
  ],
  "summary_english": "2-3 sentence summary in English",
  "summary_hindi": "2-3 sentence summary in Hindi"
}

If any field is not found, use empty list or "Not mentioned". Return ONLY valid JSON, no extra text.

TRANSCRIPT:
"""

async def extract_minutes(transcript: str) -> dict:
    """Call Sarvam-105B to extract structured minutes."""
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "model": "sarvam-105b",
        "messages": [
            {"role": "system", "content": "You are an expert panchayat secretary who extracts structured meeting minutes from transcripts."},
            {"role": "user", "content": EXTRACTION_PROMPT + transcript}
        ],
        "temperature": 0.1,
        "max_tokens": 2048,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{SARVAM_BASE}/v1/chat/completions",
            headers=headers,
            json=payload,
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Sarvam-105B error: {resp.text}")

    resp_data = resp.json()
    try:
        content = resp_data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        content = ""

    # Clean up possible markdown code fences
    content = content.strip()
    if content.startswith("```"):
        content = content.split("```")[1]
        if content.startswith("json"):
            content = content[4:]

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Fallback: return raw
        return {
            "meeting_title": "Panchayat Meeting",
            "date_mentioned": "Not specified",
            "attendees": [],
            "agenda_items": [],
            "decisions": [],
            "action_items": [],
            "summary_english": content[:500],
            "summary_hindi": "",
        }


# ─── Step 3: Sarvam Translate ─────────────────────────────────────────────────
async def translate_text(text: str, source_lang: str = "hi-IN", target_lang: str = "en-IN") -> str:
    """Translate text using Sarvam Translate API."""
    if not text.strip():
        return text

    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "input": text,
        "source_language_code": source_lang,
        "target_language_code": target_lang,
        "speaker_gender": "Male",
        "mode": "formal",
        "model": "mayura:v1",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SARVAM_BASE}/translate",
            headers=headers,
            json=payload,
        )

    if resp.status_code != 200:
        return text  # Fallback: return original

    return resp.json().get("translated_text", text)


# ─── Step 4: Bulbul TTS ───────────────────────────────────────────────────────
async def generate_audio_summary(summary_text: str) -> str:
    """Call Bulbul TTS, return base64 audio string."""
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": [summary_text[:500]],  # limit length
        "target_language_code": "hi-IN",
        "speaker": "ritu",
        "model": "bulbul:v3",
        "enable_preprocessing": True,
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{SARVAM_BASE}/text-to-speech",
            headers=headers,
            json=payload,
        )

    if resp.status_code != 200:
        return ""

    audios = resp.json().get("audios", [])
    if audios:
        return audios[0]  # base64 WAV
    return ""


# ─── Step 5: Generate PDF ─────────────────────────────────────────────────────
def generate_pdf(minutes: dict, transcript: str) -> bytes:
    """Generate a bilingual PDF of the meeting minutes."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )

    styles = getSampleStyleSheet()
    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    header_style = ParagraphStyle(
        "Header",
        parent=styles["Title"],
        fontSize=20,
        textColor=colors.HexColor("#1a5276"),
        spaceAfter=6,
    )
    sub_style = ParagraphStyle(
        "Sub",
        parent=styles["Normal"],
        fontSize=11,
        textColor=colors.HexColor("#555555"),
        spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=colors.HexColor("#1a5276"),
        spaceBefore=12,
        spaceAfter=4,
        borderPad=4,
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["Normal"],
        fontSize=10,
        leading=16,
        spaceAfter=4,
    )

    # Emoji-safe title
    story.append(Paragraph("🏛️ Panchayat Meeting Minutes", header_style))
    story.append(Paragraph(f"<b>ग्राम पंचायत बैठक की कार्यवाही</b>", sub_style))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a5276")))
    story.append(Spacer(1, 0.3*cm))

    # ── Meta Info ─────────────────────────────────────────────────────────────
    meta = [
        ["Meeting Title", minutes.get("meeting_title", "Panchayat Meeting")],
        ["Date", minutes.get("date_mentioned", "Not specified")],
        ["Attendees", ", ".join(minutes.get("attendees", [])) or "See transcript"],
    ]
    meta_table = Table(meta, colWidths=[4*cm, 13*cm])
    meta_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#d6eaf8")),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#aab7b8")),
        ("ROWBACKGROUNDS", (1, 0), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 0.4*cm))

    # ── Summary ───────────────────────────────────────────────────────────────
    story.append(Paragraph("📋 Summary (English)", section_style))
    story.append(Paragraph(minutes.get("summary_english", ""), body_style))

    story.append(Paragraph("📋 सारांश (Hindi)", section_style))
    story.append(Paragraph(minutes.get("summary_hindi", ""), body_style))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aab7b8")))

    # ── Agenda Items ──────────────────────────────────────────────────────────
    agenda = minutes.get("agenda_items", [])
    if agenda:
        story.append(Paragraph("📌 Agenda Items", section_style))
        for i, item in enumerate(agenda, 1):
            story.append(Paragraph(f"{i}. {item}", body_style))

    # ── Decisions ─────────────────────────────────────────────────────────────
    decisions = minutes.get("decisions", [])
    if decisions:
        story.append(Paragraph("✅ Decisions Taken / लिए गए निर्णय", section_style))
        dec_data = [["#", "Decision", "Details"]]
        for i, d in enumerate(decisions, 1):
            dec_data.append([
                str(i),
                d.get("decision", ""),
                d.get("details", ""),
            ])
        dec_table = Table(dec_data, colWidths=[1*cm, 7*cm, 9*cm])
        dec_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#aab7b8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eaf4fb")]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("WORDWRAP", (0, 0), (-1, -1), True),
        ]))
        story.append(dec_table)

    # ── Action Items ──────────────────────────────────────────────────────────
    actions = minutes.get("action_items", [])
    if actions:
        story.append(Paragraph("🎯 Action Items / कार्य योजना", section_style))
        act_data = [["#", "Action", "Responsible", "Deadline"]]
        for i, a in enumerate(actions, 1):
            act_data.append([
                str(i),
                a.get("action", ""),
                a.get("responsible", "TBD"),
                a.get("deadline", "TBD"),
            ])
        act_table = Table(act_data, colWidths=[1*cm, 8*cm, 5*cm, 3*cm])
        act_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e8449")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#aab7b8")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eafaf1")]),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(act_table)

    # ── Raw Transcript ────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#aab7b8")))
    story.append(Paragraph("🎙️ Raw Transcript / मूल प्रतिलेख", section_style))
    transcript_style = ParagraphStyle(
        "Transcript",
        parent=styles["Normal"],
        fontSize=9,
        leading=14,
        textColor=colors.HexColor("#555555"),
        backColor=colors.HexColor("#f8f9fa"),
        borderPad=8,
    )
    story.append(Paragraph(transcript[:3000], transcript_style))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5*cm))
    footer_style = ParagraphStyle(
        "Footer",
        parent=styles["Normal"],
        fontSize=8,
        textColor=colors.HexColor("#888888"),
        alignment=1,
    )
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dddddd")))
    story.append(Paragraph(
        "Generated by Panchayat Minutes Generator • Powered by Sarvam AI (Saaras + Sarvam-105B + Bulbul) • Sarvam Buildathon 2024",
        footer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer.read()


# ─── Main Endpoint ────────────────────────────────────────────────────────────
@app.post("/process")
async def process_meeting(audio: UploadFile = File(...)):
    """
    Full pipeline:
    1. Saaras STT → transcript
    2. Sarvam-105B → structured minutes
    3. Sarvam Translate → Hindi
    4. Bulbul TTS → audio summary
    5. PDF generation
    """
    audio_bytes = await audio.read()

    # 1. Transcribe
    stt_result = await transcribe_audio(audio_bytes, audio.filename or "meeting.wav")
    transcript = stt_result["transcript"]

    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Could not transcribe audio. Please try again with clearer audio.")

    # 2. Extract minutes
    minutes = await extract_minutes(transcript)

    # 3. Generate audio summary (Hindi)
    summary_for_audio = minutes.get("summary_hindi") or minutes.get("summary_english", "")
    audio_b64 = await generate_audio_summary(summary_for_audio)

    # 4. Save PDF to temp file
    pdf_bytes = generate_pdf(minutes, transcript)
    pdf_path = os.path.join(tempfile.gettempdir(), "panchayat_minutes.pdf")
    with open(pdf_path, "wb") as f:
        f.write(pdf_bytes)

    return JSONResponse({
        "transcript": transcript,
        "minutes": minutes,
        "audio_summary_b64": audio_b64,
        "pdf_ready": True,
    })


@app.get("/download-pdf")
async def download_pdf():
    pdf_path = os.path.join(tempfile.gettempdir(), "panchayat_minutes.pdf")
    if not os.path.exists(pdf_path):
        raise HTTPException(status_code=404, detail="PDF not yet generated. Process audio first.")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename="panchayat_minutes.pdf"
    )
