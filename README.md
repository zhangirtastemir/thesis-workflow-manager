# Thesis Workflow Manager

A web application for managing thesis proposals, assignments, milestones, and submissions in a university setting.

---

## How to Run This Application (Step-by-Step)

### Step 1: Install Python

This application requires **Python** (a programming language) to be installed on your computer.

#### On Windows:
1. Open your web browser and go to: https://www.python.org/downloads/
2. Click the big yellow **"Download Python 3.x.x"** button.
3. Open the downloaded file to start the installer.
4. **IMPORTANT:** On the first screen of the installer, check the box that says **"Add Python to PATH"** at the bottom — this is required.
5. Click **"Install Now"** and wait for it to finish.
6. Click **"Close"** when done.

#### On Mac:
1. Open your web browser and go to: https://www.python.org/downloads/
2. Click the big yellow **"Download Python 3.x.x"** button.
3. Open the downloaded `.pkg` file and follow the installer steps.
4. Click **"Continue"** through each step, then **"Install"**, and finally **"Close"**.

---

### Step 2: Unzip the Project

1. Find the `.zip` file you received.
2. **On Windows:** Right-click the zip file → **"Extract All..."** → click **"Extract"**.
3. **On Mac:** Double-click the zip file. A folder will appear next to it.
4. Remember where this folder is (e.g., on your Desktop).

---

### Step 3: Open the Terminal (Command Prompt)

You will type a few commands to start the application.

#### On Windows:
1. Press the **Windows key** on your keyboard.
2. Type **cmd** and press **Enter**. A black window will open — this is the Command Prompt.

#### On Mac:
1. Press **Command + Space** to open Spotlight Search.
2. Type **Terminal** and press **Enter**. A window will open — this is the Terminal.

---

### Step 4: Navigate to the Project Folder

In the terminal window, type the following command and press **Enter**.

Replace the path with the actual location of your unzipped folder.

#### On Windows (example):
```
cd Desktop\Case Study 2
```

#### On Mac (example):
```
cd Desktop/Case\ Study\ 2
```

> **Tip:** If you are not sure about the exact path, you can type `cd ` (with a space after it) and then **drag and drop** the project folder into the terminal window. The path will be filled in automatically. Then press **Enter**.

---

### Step 5: Install the Required Library

Type the following command and press **Enter**:

#### On Windows:
```
pip install Flask==3.1.0
```

#### On Mac:
```
pip3 install Flask==3.1.0
```

Wait a few seconds. You will see some text scrolling — that is normal. When it finishes and you see a new line ready for input, proceed to the next step.

> **If you get an error** saying `pip is not recognized` or `command not found`, try using `python -m pip install Flask==3.1.0` (Windows) or `python3 -m pip install Flask==3.1.0` (Mac) instead.

---

### Step 6: Run the Application

Type the following command and press **Enter**:

#### On Windows:
```
python app.py
```

#### On Mac:
```
python3 app.py
```

You should see output similar to:
```
 * Running on http://127.0.0.1:5000
```

**Leave this terminal window open.** The application is now running.

---

### Step 7: Open the Application in Your Browser

1. Open your web browser (Chrome, Firefox, Safari, Edge — any will work).
2. In the address bar at the top, type the following and press **Enter**:

```
http://127.0.0.1:5000
```

You should now see the **Thesis Workflow Manager** dashboard with sample data already loaded.

---

### Step 8: When You Are Done

To stop the application:

1. Go back to the terminal window.
2. Press **Ctrl + C** on your keyboard (hold the Ctrl key and press C).
3. You can now close the terminal window.

---

## Features

- **Dashboard** — status counts and recently updated theses
- **Thesis CRUD** — create, edit, delete theses
- **Status workflow** — Draft → Submitted → UnderReview → Approved → FinalSubmitted → Completed (with RevisionRequested loop)
- **Supervisor assignment** — assign or reassign supervisors
- **Milestones** — add, edit, delete, and transition milestone statuses (Planned → InProgress → Submitted → Accepted)
- **Submissions** — record proposal/interim/final submissions with optional URL
- **Status history** — full audit trail of thesis status changes
- **Filtering** — filter thesis list by status

## Seed Data

The app ships with 5 students, 3 supervisors, 5 theses (across different statuses), 7 milestones, and 4 submissions pre-loaded.

## Tech Stack

- Python 3 + Flask
- SQLite (file: `thesis.db`, auto-created)
- Server-side rendered HTML (Jinja2 templates, no JS framework)
