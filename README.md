# KJSIT Feedback Portal

This project uses **Django** for the backend and **React + Vite + TSX** for the frontend. A custom Python script automates:

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
- UV

### UV
    curl -LsSf https://astral.sh/uv/install.sh | sh 
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

    uv install

### Frontend dependencies

    cd kjsitfeedbackvite
    npm install

---

## 🚀 How to Run

### Run Both Frontend and Backend

    uv run.py

### Run Only Backend (Django)

    uv run.py --backend

### Run Only Frontend (React + Vite)

    iv run.py --frontend

---

## 🛠 What the Script Does

1. Runs Django `makemigrations` and `migrate`
2. Starts the backend with `uv run manage.py runserver`
3. Starts React frontend with `npm run dev` inside `kjsitfeedbackvite`
4. Outputs are prefixed as `[BACKEND]` or `[FRONTEND]`

---

## 📝 License

This project is licensed under the MIT License.
