# 🏛️ Panchayat Minutes Generator

> **Turn chaotic village meetings into official government records — powered by Sarvam AI**

Built at **Sarvam Buildathon 2026** ⚡

![Sarvam AI](https://img.shields.io/badge/Powered%20by-Sarvam%20AI-blue)
![Python](https://img.shields.io/badge/Python-3.11-green)
![FastAPI](https://img.shields.io/badge/FastAPI-Backend-teal)

## 🎯 Problem

Millions of Panchayat meetings happen weekly across India with **zero documentation**. Decisions are lost, action items forgotten, and citizens have no official record of what was discussed.

## 💡 Solution

Upload or record a panchayat meeting audio (in Hindi, Hinglish, or any Indic language) and get:

- 📝 **Full transcript** with multi-speaker identification
- 📋 **Structured minutes** — agenda, decisions, action items with owners & deadlines
- 🌐 **Bilingual output** — English + Hindi summaries
- 🔊 **Audio summary** — Bulbul reads back the Hindi summary for illiterate members
- 📄 **Official PDF** — downloadable bilingual meeting minutes

## 🏗️ Architecture

```
[Upload/Record Audio]
       ↓
  Saaras v4 (Multi-Speaker STT) → raw transcript with speaker labels
       ↓
  Sarvam-105B → extract decisions, action items, attendees (JSON)
       ↓
  Bulbul v3 (TTS) → spoken Hindi summary
       ↓
  ReportLab → bilingual PDF minutes
       ↓
  [Download PDF] [Play Audio] [View Results]
```

## 🧠 Sarvam Models Used

| Model | Purpose |
|-------|---------|
| **Saaras v4 Multi-Speaker** | Speech-to-text with speaker diarization |
| **Sarvam-105B** | Structured extraction of meeting minutes |
| **Bulbul v3** | Text-to-speech for Hindi audio summary |
| **Mayura v1** | Hindi ↔ English translation |

## 🚀 Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/YOUR_USERNAME/panchayat-minutes.git
cd panchayat-minutes
pip install -r requirements.txt
```

### 2. Set API Key
```bash
cp .env.example .env
# Edit .env and add your Sarvam API key
```

### 3. Run
```bash
uvicorn main:app --reload --port 8000
```

### 4. Open
Visit **http://localhost:8000** — upload audio or record live!

## 📂 Project Structure

```
panchayat-minutes/
├── main.py                  # FastAPI backend (all Sarvam API calls + PDF)
├── index.html               # Single-page UI (upload, record, results)
├── gen_test_audio.py         # Generate single-speaker test audio
├── gen_multi_speaker.py      # Generate multi-speaker test audio
├── requirements.txt          # Python dependencies
├── .env.example              # API key template
└── .gitignore
```

## 🎥 Demo

1. Drop any Hindi meeting audio onto the upload zone
2. Watch the 4-step progress: **Saaras → Sarvam-105B → Bulbul → PDF**
3. View structured decisions & action items tables
4. Listen to the spoken Hindi summary
5. Download the bilingual PDF

## 🌍 Impact

- **Governance transparency** — every meeting gets documented
- **Accessibility** — audio summaries for illiterate members
- **Bilingual** — works in Hindi with English translations
- **Zero infrastructure** — runs on any phone/laptop with internet

## 👨‍💻 Built By

**Basavaraj N** — Sarvam Buildathon 2026

## 📜 License

MIT
