# 💊 RxGuardian — FastAPI Backend

Complete medicine-tracking backend built with **FastAPI**, **MongoDB** (Motor async), **SQLite** (SQLAlchemy async), and **Docker**.

---

## 📁 Project Structure

```
rxguardian-backend/
├── app/
│   ├── main.py               ← FastAPI app factory, routers, middleware
│   ├── config.py             ← Pydantic-settings (reads .env)
│   ├── auth/
│   │   ├── jwt_handler.py    ← JWT create / decode
│   │   └── dependencies.py   ← get_current_user FastAPI dependency
│   ├── database/
│   │   ├── mongo.py          ← Motor async MongoDB connection
│   │   └── sqlite.py         ← SQLAlchemy async SQLite engine + session
│   ├── models/
│   │   └── sqlite_models.py  ← SQLAlchemy ORM (ChatMessage, DailyTracking)
│   ├── routes/
│   │   ├── auth_routes.py
│   │   ├── medicine_routes.py
│   │   ├── chat_routes.py
│   │   └── tracking_routes.py
│   ├── schemas/              ← Pydantic request/response models
│   ├── services/             ← Business logic layer
│   └── utils/
│       ├── password.py       ← bcrypt helpers
│       ├── mongo_helpers.py  ← doc normalisation (_id → id)
│       └── ocr.py            ← Tesseract OCR for prescription images
├── logs/                     ← Log files (auto-created)
├── Dockerfile                ← Multi-stage Docker build
├── docker-compose.yml        ← api + mongo + mongo-express
├── requirements.txt
└── .env                      ← Environment variables (copy & edit)
```

---

## 🖥️ What You Need Installed on Your PC

| Tool | Why | Install |
|---|---|---|
| **Docker Desktop** | Runs all containers | https://www.docker.com/products/docker-desktop |
| **Docker Compose** | Bundled with Docker Desktop | ✅ Already included |
| *(optional)* **curl / Postman** | Testing API manually | https://www.postman.com |
| *(optional)* **MongoDB Compass** | GUI for MongoDB data | https://www.mongodb.com/products/compass |

> ✅ **That's it.** No Python, no pip, no venv needed on your machine. Everything runs inside Docker.

---

## 🚀 Quick Start

### 1. Clone / copy the project
```bash
# If you have git
git clone <your-repo-url> rxguardian-backend
cd rxguardian-backend

# OR just navigate to the folder
cd rxguardian-backend
```

### 2. Edit the `.env` file (optional for dev, required for prod)
```bash
# The .env file is pre-filled with safe dev defaults.
# For production, change JWT_SECRET_KEY to a long random string.
nano .env      # or open in any editor
```

### 3. Build and start all containers
```bash
docker compose up --build
```

The first build downloads the Python base image, installs Tesseract OCR, and installs all pip packages. **This takes ~3–5 minutes the first time.** Subsequent starts are instant.

### 4. Watch for these success messages in the terminal
```
rxguardian_api   | ✓ MongoDB connected
rxguardian_api   | ✓ SQLite tables created
rxguardian_api   | Uvicorn running on http://0.0.0.0:8000
```

---

## ✅ Verifying the Backend is Running

### A) Browser — Swagger UI
Open: **http://localhost:8000/docs**

You should see the full interactive API documentation.

### B) Health Check endpoint
```bash
curl http://localhost:8000/health
```
Expected response:
```json
{"status": "ok", "version": "1.0.0", "app": "RxGuardian"}
```

### C) Mongo Express (database admin UI)
Open: **http://localhost:8081**
- Username: `admin`
- Password: `rxguardian123`

You can browse collections, run queries, and verify data is being stored.

### D) Test the full auth flow with curl
```bash
# 1. Register a new user
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name":"Ayaan Khan","email":"ayaan@test.com","password":"secret123"}'

# 2. Copy the access_token from the response, then:
TOKEN="paste_your_token_here"

# 3. Add a medicine
curl -X POST http://localhost:8000/api/v1/medicines/manual \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Metformin",
    "dosage": "500mg",
    "frequency": "2x Daily",
    "time_slots": [{"time": "08:00 AM", "instructions": "After meal"}],
    "instructions": "Take with water"
  }'

# 4. List medicines
curl http://localhost:8000/api/v1/medicines \
  -H "Authorization: Bearer $TOKEN"

# 5. Mark medicine as taken (replace MEDICINE_ID)
curl -X POST http://localhost:8000/api/v1/track/take \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"medicine_id": "MEDICINE_ID", "date": "2026-04-18"}'

# 6. Get today's status
curl http://localhost:8000/api/v1/track/today \
  -H "Authorization: Bearer $TOKEN"

# 7. Chat with AI
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "What are the side effects of Metformin?"}'
```

---

## 📡 API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register` | ❌ | Register new user |
| POST | `/api/v1/auth/login` | ❌ | Login, get JWT |
| POST | `/api/v1/medicines/manual` | ✅ | Add medicine manually |
| POST | `/api/v1/medicines/from-image` | ✅ | Add via prescription photo (OCR) |
| GET | `/api/v1/medicines` | ✅ | List all medicines |
| GET | `/api/v1/medicines/{id}` | ✅ | Get single medicine |
| PUT | `/api/v1/medicines/{id}` | ✅ | Update medicine |
| DELETE | `/api/v1/medicines/{id}` | ✅ | Delete medicine |
| POST | `/api/v1/chat` | ✅ | Send message to AI |
| GET | `/api/v1/chat/history` | ✅ | Fetch chat history |
| POST | `/api/v1/track/take` | ✅ | Mark medicine as taken |
| GET | `/api/v1/track/today` | ✅ | Today's adherence status |
| GET | `/health` | ❌ | Health check |

---

## 🔄 SQLite → MongoDB Sync Logic

When you call `POST /api/v1/track/take`:
1. The dose is recorded in **SQLite** (`daily_tracking` table).
2. The backend checks: *are ALL medicines for that user+date marked taken?*
3. If **yes** → the day's records are written to **MongoDB** (`daily_logs` collection) and deleted from SQLite.
4. The response includes `synced_to_mongo: true/false`.

---

## 🐳 Docker Commands Reference

```bash
# Start in background (detached)
docker compose up -d --build

# View live logs
docker compose logs -f api

# View only MongoDB logs
docker compose logs -f mongo

# Stop everything
docker compose down

# Stop AND delete all data volumes (fresh start)
docker compose down -v

# Rebuild just the API image (after code changes)
docker compose up --build api

# Open a shell inside the running API container
docker exec -it rxguardian_api bash
```

---

## 🔧 Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://mongo:27017` | MongoDB connection string |
| `MONGO_DB_NAME` | `rxguardian` | Database name |
| `SQLITE_DB_PATH` | `./rxguardian_local.db` | SQLite file path |
| `JWT_SECRET_KEY` | (change this!) | Secret for signing tokens |
| `JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `JWT_EXPIRE_MINUTES` | `10080` (7 days) | Token expiry |
| `ALLOWED_ORIGINS` | `localhost:3000,8081` | CORS allowed origins |

---

## 🏗️ Connecting from React Native (Expo)

```javascript
// In your Expo app — use your machine's local IP (not localhost)
const API_BASE = "http://192.168.x.x:8000/api/v1";

// Login example
const res = await fetch(`${API_BASE}/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: "ayaan@test.com", password: "secret123" }),
});
const { access_token } = await res.json();

// Authenticated request
const meds = await fetch(`${API_BASE}/medicines`, {
  headers: { Authorization: `Bearer ${access_token}` },
});
```

> 💡 Find your local IP: run `ipconfig` (Windows) or `ifconfig` (Mac/Linux).
> On Android emulator use `http://10.0.2.2:8000`.

---

## 🩺 Troubleshooting

| Problem | Fix |
|---|---|
| `Connection refused` on port 8000 | Check `docker compose up` is still running |
| MongoDB ping fails on startup | Wait 10–15s; Mongo takes time to initialise |
| OCR returns "simulated" result | Tesseract is bundled in Docker — it will work inside the container |
| `JWT_SECRET_KEY` warning | Change it in `.env` before going to production |
| Port 8081 already in use | Change Mongo Express port in `docker-compose.yml` |
