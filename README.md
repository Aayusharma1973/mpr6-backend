# 🛡️ RxGuardian — Advanced AI Medicine Tracking Backend

RxGuardian is a sophisticated medical assistant backend that combines **Large Language Models (LLMs)**, **Vision Language Models (VLMs)**, and **automated adherence tracking** to help users manage their prescriptions safely and effectively.

Built with **FastAPI**, **MongoDB**, **SQLite**, and powered by **Ollama (Qwen2.5)** and **Qwen2-VL**.

---

## ✨ Key Features

- 👁️ **Smart Prescription Scan**: Vision-based medicine extraction using `Qwen2-VL-2B` (OCR).
- 🤖 **RxGuardian AI Chat**: Interactive drug Q&A and explanation powered by `qwen2.5:3b`.
- 💊 **Adherence Prediction**: AI-driven insights that predict the next likely missed dose based on tracking history.
- ⚠️ **Safety Validator**: Real-time interaction alerts and side-effect analysis for new medications.
- 🛒 **PharmEasy Integration**: Automatic product search and price comparison for detected medicines.
- 📅 **Hybrid Adherence Tracking**: Fast local tracking (SQLite) with automatic cloud sync (MongoDB) upon day completion.
- 🔐 **Secure by Default**: JWT-based authentication with protected routes.

---

## 🏗️ Architecture & Stack

| Component | Technology | Role |
| :--- | :--- | :--- |
| **Framework** | FastAPI | High-performance async API |
| **Primary Database** | MongoDB (Motor) | Cloud-synced adherence logs & user data |
| **Local Cache** | SQLite (SQLAlchemy) | Active tracking & chat history |
| **VLM (Vision)** | Qwen2-VL-2B | Prescription image analysis |
| **LLM (Chat/Logic)** | Qwen2.5-3B (Ollama) | Natural language interaction & insights |
| **External API** | PharmEasy | Live medicine product data |
| **Deployment** | Docker & Compose | Containerized orchestration |

---

## 🚀 Quick Start (Docker)

### 1. Prerequisites
- **Docker Desktop** installed.
- **NVIDIA GPU** (Recommended for Qwen2-VL performance).
- **Ollama** installed on the host machine (if not running inside Docker).

### 2. Environment Setup
Create a `.env` file in the root directory:
```env
MONGO_URI=mongodb+srv://<user>:<password>@cluster.mongodb.net/rxguardian
JWT_SECRET_KEY=your_random_secret_string
HF_TOKEN=your_huggingface_token
ALLOWED_ORIGINS=http://localhost:8081,exp://localhost:8081
```

### 3. Launch
```bash
docker compose up --build -d
```
*Note: The first build will take several minutes as it installs Tesseract OCR and CUDA-enabled PyTorch.*

---

## 📡 API Reference

### 🤖 AI Insights (`/api/v1/ai`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| POST | `/interaction-alert` | Checks if a new medicine conflicts with user profile/meds. |
| POST | `/suggestions` | Bioavailability and lifestyle timing tips (e.g., "Take with water"). |
| POST | `/insights` | Adherence analysis and missed dose prediction. |
| POST | `/side-effects` | Detailed side-effect profile for specific medications. |

### 💬 Chat System (`/api/v1/chat`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| POST | `/` | Text-only message to RxGuardian AI. |
| POST | `/with-image` | Upload a prescription image and ask questions about it. |
| GET | `/history` | Fetch paginated chat history. |

### 💊 Medicine Management (`/api/v1/medicines`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| POST | `/scan-only` | Preview detected medicines from an image (No DB write). |
| POST | `/from-image` | Scan and automatically save all detected medicines. |
| POST | `/manual` | Add a medicine record manually. |
| GET | `/` | List all active medications. |

### 📅 Adherence Tracking (`/api/v1/track`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| POST | `/take` | Mark a specific dose as taken. |
| GET | `/today` | Get current adherence status for the day. |

---

## 📱 Mobile Integration (React Native / Expo)

When connecting from a mobile device or emulator, use your machine's **Local IP Address** instead of `localhost`.

- **Android Emulator:** `http://10.0.2.2:8000`
- **Physical Device:** `http://192.168.x.x:8000`

### CORS Configuration
Ensure your device's URL is added to `ALLOWED_ORIGINS` in `.env`:
```env
ALLOWED_ORIGINS=http://192.168.1.5:8081,exp://192.168.1.5:8081
```

---

## 🩺 System Health & Monitoring
- **Swagger UI:** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/health` (Reports VLM model loading status)
- **DB Admin:** `http://localhost:8081` (Mongo Express)

---

## 🤝 Troubleshooting

| Issue | Solution |
| :--- | :--- |
| **Qwen Model Loading** | The VLM takes ~60s to load into GPU memory. Check `/health` status. |
| **Ollama Connection** | Ensure Ollama is running on the host and reachable via `host.docker.internal`. |
| **Permission Denied** | The Dockerfile uses a non-root user (`rxguardian`). Ensure `hf_cache` volume has correct permissions. |
| **CORS Errors** | Verify your React Native dev URL matches the `ALLOWED_ORIGINS` exactly. |
