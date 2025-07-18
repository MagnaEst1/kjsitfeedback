#!/bin/bash

cat > README.md << 'EOF'
# KJSIT Feedback Portal

This project uses **Django** for the backend and **React + Vite** for the frontend. A custom Python script automates:

- Django `makemigrations` and `migrate`
- Starting the Django development server
- Starting the React + Vite frontend dev server
- Optionally running only one side

---

## 📁 Project Structure

    .
    ├── manage.py
    ├── kjsitfeedback/         # Django project
    ├── kjsitfeedbackvite/     # React + Vite frontend
    ├── run.py                 # Python script to launch servers
    └── README.md

---

## ⚙️ Prerequisites

- Python 3.10+
- Node.js 18+
- Django
- Vite + React

### Python dependencies

    pip install -r requirements.txt

### Frontend dependencies

    cd kjsitfeedbackvite
    npm install

---

## 🚀 How to Run

### Run Both Frontend and Backend

    python run.py

### Run Only Backend (Django)

    python run.py --backend

### Run Only Frontend (React + Vite)

    python run.py --frontend

---

## 🛠 What the Script Does

1. Runs Django `makemigrations` and `migrate`
2. Starts the backend with `uv run manage.py runserver`
3. Starts React frontend with `npm run dev` inside `kjsitfeedbackvite`
4. Outputs are prefixed as `[BACKEND]` or `[FRONTEND]`

---

## 🧪 Notes

- Shell-safe for Windows and Unix
- Threads run both servers in parallel
- Modify paths or commands inside `run.py` as needed

---

## 💡 Tips

- Use `python3` instead of `python` on Unix systems if needed
- Create `.env` files for sensitive config
- Use `vite build` and `gunicorn`/`uvicorn` for production

---

## 📝 License

This project is licensed under the MIT License.
EOF

echo "✅ README.md generated successfully."
