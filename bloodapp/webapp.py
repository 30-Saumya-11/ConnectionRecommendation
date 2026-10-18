"""Production-grade Multi-User Web Application for SonetQ BloodConnect.

Integrates:
  1. OS: Priority Scheduling (Emergency 0 > Urgent 1 > Routine 2), thread-safe queue.
  2. DBMS: ACID Atomic Allocation Transactions, Foreign Keys, Row-Locking, Audit Trail.
  3. ML: Dynamic Graph Link Prediction with Interactive Visual Connectivity Graph
     - Patients represented as Blue Dots (🔵)
     - Voluntary Donors represented as Red Dots (🔴)
     - Edges representing topological & social network connectivity
  4. Multi-User Experience:
     - Distinct Portals for Hospital Staff, Patients (Acceptors), Voluntary Donors, and Admin.
     - Personalized data isolation (Patients only see their requests; Donors see matching appeals).
     - Self-Registration (Sign Up) for any new Patient, Donor, or Staff user.
     - One-click demo credentials for effortless evaluation/viva demonstrations.
"""
import functools
import json
import math
import os
import threading
from datetime import date, timedelta
from flask import Flask, jsonify, request, session

from sonetq.cache import SharedSnapshotStore
from . import rules
from .bdb import BloodDB
from .recommender import DonorRecommender
from .world import CITIES, TODAY, build_world

STATE = {
    "lock": threading.Lock(),
    "clock": 0,
    "store": None,
    "path": None,
    "latest": 12,
}

app = Flask(__name__)
app.secret_key = os.urandom(24)


def _db():
    return BloodDB("sqlite", STATE["path"])


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if "user" not in session:
            return jsonify({"error": "Authentication required. Please log in."}), 401
        return f(*args, **kwargs)
    return wrapper


def role_required(*allowed_roles):
    def decorator(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            if "user" not in session:
                return jsonify({"error": "Authentication required. Please log in."}), 401
            role = session["user"].get("role")
            if role not in allowed_roles:
                return jsonify({"error": f"Access denied. Requires one of roles: {', '.join(allowed_roles)}"}), 403
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ==============================================================================
# HTML FRONTEND TEMPLATE
# ==============================================================================
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SonetQ BloodConnect - Priority Blood Allocation & ML Donor Network</title>
<style>
  :root {
    --primary: #dc2626;
    --primary-hover: #b91c1c;
    --primary-soft: #fef2f2;
    --dark: #0f172a;
    --slate: #334155;
    --muted: #64748b;
    --border: #e2e8f0;
    --bg: #f8fafc;
    --card: #ffffff;
    --emerald: #059669;
    --emerald-soft: #ecfdf5;
    --amber: #d97706;
    --amber-soft: #fffbeb;
    --blue: #2563eb;
    --blue-soft: #eff6ff;
    --rose: #e11d48;
    --rose-soft: #fff1f2;
    --purple: #7c3aed;
    --purple-soft: #f5f3ff;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; }
  body { background: var(--bg); color: var(--dark); line-height: 1.5; min-height: 100vh; display: flex; flex-direction: column; }
  
  /* Navbar */
  header { background: var(--card); border-bottom: 1px solid var(--border); padding: 12px 28px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 1px 3px rgba(0,0,0,0.03); }
  .brand { display: flex; align-items: center; gap: 12px; cursor: pointer; }
  .logo-icon { width: 40px; height: 40px; background: var(--primary); color: white; border-radius: 10px; display: flex; align-items: center; justify-content: center; font-size: 22px; font-weight: bold; }
  .brand h1 { font-size: 18px; font-weight: 700; color: var(--dark); }
  .brand span { font-size: 12px; color: var(--muted); }
  
  .user-bar { display: flex; align-items: center; gap: 14px; }
  
  /* Nav Tabs */
  .nav-tabs { display: flex; align-items: center; gap: 6px; background: #f1f5f9; padding: 4px; border-radius: 8px; }
  .nav-tab-btn { border: none; background: transparent; padding: 6px 14px; font-size: 12px; font-weight: 700; color: var(--muted); border-radius: 6px; cursor: pointer; transition: all 0.15s; }
  .nav-tab-btn.active { background: white; color: var(--dark); box-shadow: 0 1px 2px rgba(0,0,0,0.08); }

  /* Badges */
  .badge { display: inline-flex; align-items: center; padding: 4px 10px; border-radius: 9999px; font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.4px; }
  .badge-staff { background: var(--blue-soft); color: var(--blue); border: 1px solid #bfdbfe; }
  .badge-user { background: var(--emerald-soft); color: var(--emerald); border: 1px solid #a7f3d0; }
  .badge-donor { background: var(--rose-soft); color: var(--rose); border: 1px solid #fecdd3; }
  .badge-admin { background: var(--purple-soft); color: var(--purple); border: 1px solid #ddd6fe; }
  
  .badge-prio-0 { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; } /* EMERGENCY */
  .badge-prio-1 { background: #fef3c7; color: #92400e; border: 1px solid #fde68a; } /* URGENT */
  .badge-prio-2 { background: #f1f5f9; color: var(--slate); border: 1px solid #cbd5e1; } /* ROUTINE */

  .badge-status-PENDING { background: var(--amber-soft); color: #b45309; }
  .badge-status-FULFILLED { background: var(--emerald-soft); color: #047857; }
  .badge-status-PARTIAL { background: #ffedd5; color: #c2410c; }

  /* Containers & Cards */
  .container { max-width: 1150px; margin: 20px auto; padding: 0 20px; width: 100%; flex: 1; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 22px; box-shadow: 0 1px 3px rgba(0,0,0,0.02); margin-bottom: 22px; }
  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
  .card-title { font-size: 16px; font-weight: 700; color: var(--dark); display: flex; align-items: center; gap: 8px; }
  .card-desc { font-size: 12px; color: var(--muted); margin-top: 2px; }

  /* Grid */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .grid-3 { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .grid-4 { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; }

  /* Stock Box */
  .stock-box { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 12px; text-align: center; }
  .stock-group { font-size: 18px; font-weight: 800; color: var(--dark); }
  .stock-count { font-size: 24px; font-weight: 800; color: var(--primary); margin: 2px 0; }
  .stock-label { font-size: 11px; color: var(--muted); text-transform: uppercase; font-weight: 600; }

  /* Buttons & Inputs */
  .btn { display: inline-flex; align-items: center; justify-content: center; gap: 6px; padding: 9px 16px; font-size: 13px; font-weight: 600; border-radius: 8px; border: none; cursor: pointer; transition: all 0.15s; }
  .btn-primary { background: var(--primary); color: white; }
  .btn-primary:hover { background: var(--primary-hover); }
  .btn-secondary { background: #f1f5f9; color: var(--dark); border: 1px solid var(--border); }
  .btn-secondary:hover { background: #e2e8f0; }
  .btn-emerald { background: var(--emerald); color: white; }
  .btn-emerald:hover { background: #059669; }
  .btn-rose { background: var(--rose); color: white; }
  .btn-rose:hover { background: #be123c; }
  .btn-blue { background: var(--blue); color: white; }
  .btn-blue:hover { background: #1d4ed8; }
  .btn-sm { padding: 5px 10px; font-size: 12px; }

  .form-group { margin-bottom: 14px; }
  label { display: block; font-size: 13px; font-weight: 600; color: var(--slate); margin-bottom: 5px; }
  input, select, textarea { width: 100%; padding: 9px 12px; border: 1px solid var(--border); border-radius: 8px; font-size: 13px; background: #fff; }
  input:focus, select:focus { outline: none; border-color: var(--primary); }

  /* Tables */
  .table-responsive { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; }
  table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
  th { background: #f8fafc; color: var(--slate); font-weight: 600; padding: 10px 14px; border-bottom: 1px solid var(--border); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
  td { padding: 10px 14px; border-bottom: 1px solid var(--border); color: var(--slate); }
  tr:last-child td { border-bottom: none; }
  tr:hover td { background: #fcfdfe; }

  /* Alerts & Modal */
  .alert { padding: 12px 16px; border-radius: 8px; font-size: 13px; margin-bottom: 16px; }
  .alert-info { background: var(--blue-soft); color: var(--blue); border: 1px solid #bfdbfe; }
  .alert-success { background: var(--emerald-soft); color: #047857; border: 1px solid #a7f3d0; }
  .alert-warning { background: var(--amber-soft); color: #92400e; border: 1px solid #fde68a; }
  .alert-danger { background: #fef2f2; color: #991b1b; border: 1px solid #fecaca; }

  .modal-overlay { position: fixed; inset: 0; background: rgba(15, 23, 42, 0.6); backdrop-filter: blur(3px); display: flex; align-items: center; justify-content: center; z-index: 1000; padding: 20px; }
  .modal-card { background: white; width: 100%; max-width: 650px; max-height: 90vh; overflow-y: auto; border-radius: 16px; padding: 26px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); border: 1px solid var(--border); }

  /* Login / Register Card */
  .auth-box { max-width: 480px; margin: 30px auto; background: white; border-radius: 16px; padding: 28px; border: 1px solid var(--border); box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05); }
  .auth-mode-switch { display: flex; background: #f1f5f9; padding: 4px; border-radius: 10px; margin-bottom: 20px; }
  .auth-mode-btn { flex: 1; padding: 8px 12px; border: none; background: transparent; font-size: 13px; font-weight: 700; color: var(--muted); border-radius: 8px; cursor: pointer; transition: all 0.2s; }
  .auth-mode-btn.active { background: white; color: var(--dark); box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  
  .auth-role-tabs { display: flex; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
  .auth-role-tab { flex: 1; text-align: center; padding: 8px 4px; font-weight: 600; font-size: 12px; color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; }
  .auth-role-tab.active { color: var(--primary); border-bottom-color: var(--primary); }

  .credential-chip { background: #f8fafc; padding: 8px 12px; border-radius: 8px; font-size: 12px; color: var(--slate); display: flex; justify-content: space-between; align-items: center; margin-top: 6px; cursor: pointer; border: 1px solid #e2e8f0; transition: all 0.15s; }
  .credential-chip:hover { background: #eff6ff; border-color: #bfdbfe; }

  /* Connection Network Pill */
  .network-path { background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 8px 12px; font-size: 12px; color: #991b1b; margin-top: 4px; display: flex; align-items: center; gap: 8px; }

  .hidden { display: none !important; }
</style>
</head>
<body>

<!-- Header -->
<header>
  <div class="brand" onclick="switchNavSection('portal')">
    <div class="logo-icon">🩸</div>
    <div>
      <h1>SonetQ BloodConnect</h1>
      <span>Smart Priority Blood Allocation & ML Donor Network</span>
    </div>
  </div>
  <div class="user-bar">
    <div id="navTabs" class="nav-tabs hidden">
      <button class="nav-tab-btn active" id="btnNavPortal" onclick="switchNavSection('portal')">📋 Dashboard</button>
      <button class="nav-tab-btn" id="btnNavGraph" onclick="switchNavSection('graph')">🌐 Connectivity Graph</button>
    </div>
    <div id="userInfo" class="hidden" style="display:flex; align-items:center; gap:12px;">
      <div style="text-align:right;">
        <div style="font-size:13px; font-weight:700;" id="userDisplay">User</div>
        <div style="font-size:11px; color:var(--muted);" id="userSubDisplay">Profile</div>
      </div>
      <span class="badge" id="roleBadge">ROLE</span>
      <button class="btn btn-secondary btn-sm" onclick="logout()">Sign Out</button>
    </div>
  </div>
</header>

<div class="container">
  <div id="toast" class="alert hidden"></div>

  <!-- ============================================================== VIEW 1: AUTHENTICATION (Login & Sign-Up Screen) -->
  <div id="view-login" class="auth-box">
    <div style="text-align: center; margin-bottom: 18px;">
      <div class="logo-icon" style="margin: 0 auto 10px auto;">🩸</div>
      <h2 style="font-size: 20px; font-weight: 700;">Welcome to BloodConnect</h2>
      <p style="font-size: 12px; color: var(--muted); margin-top: 2px;">Sign in with your role or create a new user profile</p>
    </div>

    <!-- Toggle Mode: Sign In vs Sign Up -->
    <div class="auth-mode-switch">
      <button class="auth-mode-btn active" id="btnModeLogin" onclick="setAuthMode('login')">Sign In</button>
      <button class="auth-mode-btn" id="btnModeRegister" onclick="setAuthMode('register')">Register / Sign Up</button>
    </div>

    <!-- FORM A: SIGN IN -->
    <div id="authLoginForm">
      <div class="auth-role-tabs">
        <div class="auth-role-tab active" id="tabStaffAuth" onclick="switchLoginRole('STAFF')">🏥 Staff</div>
        <div class="auth-role-tab" id="tabPatientAuth" onclick="switchLoginRole('USER')">🩸 Patient</div>
        <div class="auth-role-tab" id="tabDonorAuth" onclick="switchLoginRole('DONOR')">💖 Donor</div>
        <div class="auth-role-tab" id="tabAdminAuth" onclick="switchLoginRole('ADMIN')">👑 Admin</div>
      </div>

      <form onsubmit="handleAuthSubmit(event)">
        <div class="form-group">
          <label>Username</label>
          <input type="text" id="inputUsername" placeholder="e.g. staff" required>
        </div>
        <div class="form-group">
          <label>Password</label>
          <input type="password" id="inputPassword" placeholder="••••••••" required>
        </div>
        <button type="submit" class="btn btn-primary" style="width: 100%; margin-top: 4px;">Sign In</button>
      </form>

      <!-- Quick Demo Accounts -->
      <div style="margin-top: 20px; padding-top: 14px; border-top: 1px dashed var(--border);">
        <div style="font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; margin-bottom: 6px;">One-Click Demo Accounts (Viva / Evaluation):</div>
        <div class="credential-chip" onclick="fillCreds('staff', 'staff123', 'STAFF')">
          <span>🏥 <b>Hospital Staff</b> (Doon Blood Bank &bull; <code>staff</code>)</span>
          <span style="color:var(--primary); font-weight:700;">Login &rarr;</span>
        </div>
        <div class="credential-chip" onclick="fillCreds('rahul', 'user123', 'USER')">
          <span>🩸 <b>Patient 1: Rahul Sharma</b> (Group O+ &bull; <code>rahul</code>)</span>
          <span style="color:var(--primary); font-weight:700;">Login &rarr;</span>
        </div>
        <div class="credential-chip" onclick="fillCreds('priya', 'user123', 'USER')">
          <span>🩸 <b>Patient 2: Priya Patel</b> (Group A+ &bull; <code>priya</code>)</span>
          <span style="color:var(--primary); font-weight:700;">Login &rarr;</span>
        </div>
        <div class="credential-chip" onclick="fillCreds('vikram', 'donor123', 'DONOR')">
          <span>💖 <b>Donor 1: Vikram Malhotra</b> (Eligible O+ &bull; <code>vikram</code>)</span>
          <span style="color:var(--primary); font-weight:700;">Login &rarr;</span>
        </div>
        <div class="credential-chip" onclick="fillCreds('sneha', 'donor123', 'DONOR')">
          <span>💖 <b>Donor 2: Sneha Rawat</b> (Eligible B+ &bull; <code>sneha</code>)</span>
          <span style="color:var(--primary); font-weight:700;">Login &rarr;</span>
        </div>
        <div class="credential-chip" onclick="fillCreds('admin', 'admin123', 'ADMIN')">
          <span>👑 <b>Administrator</b> (DBMS Audit &bull; <code>admin</code>)</span>
          <span style="color:var(--primary); font-weight:700;">Login &rarr;</span>
        </div>
      </div>
    </div>

    <!-- FORM B: REGISTER NEW USER (SIGN UP) -->
    <div id="authRegisterForm" class="hidden">
      <form onsubmit="handleRegisterSubmit(event)">
        <div class="form-group">
          <label>Full Name</label>
          <input type="text" id="regName" placeholder="e.g. Kavya Rathi" required>
        </div>
        <div class="grid-2">
          <div class="form-group">
            <label>Username</label>
            <input type="text" id="regUsername" placeholder="e.g. kavya" required>
          </div>
          <div class="form-group">
            <label>Password</label>
            <input type="password" id="regPassword" placeholder="••••••••" required>
          </div>
        </div>
        <div class="form-group">
          <label>Account Role</label>
          <select id="regRole" required onchange="toggleRegFields()">
            <option value="USER">🩸 Patient / Acceptor (Request Blood)</option>
            <option value="DONOR">💖 Voluntary Donor (Donate Blood)</option>
            <option value="STAFF">🏥 Hospital Blood Bank Staff</option>
          </select>
        </div>
        <div id="regMedicalFields">
          <div class="grid-3">
            <div class="form-group">
              <label>Blood Group</label>
              <select id="regBloodGroup"></select>
            </div>
            <div class="form-group">
              <label>City</label>
              <select id="regCity"></select>
            </div>
            <div class="form-group">
              <label>Age (Years)</label>
              <input type="number" id="regAge" value="22" min="18" max="65" required>
            </div>
          </div>
        </div>
        <button type="submit" class="btn btn-primary" style="width: 100%; margin-top: 6px;">Register & Enter Portal</button>
      </form>
    </div>
  </div>

  <!-- ============================================================== VIEW 2: HOSPITAL STAFF DASHBOARD -->
  <div id="view-hospital" class="hidden">
    <!-- Top Stock Grid -->
    <div class="card">
      <div class="card-header">
        <div>
          <h2 class="card-title">🏥 Blood Bank Storage Inventory</h2>
          <p class="card-desc">Current safe, non-expired blood units in hospital blood bank storage.</p>
        </div>
        <button class="btn btn-primary btn-sm" onclick="showAddStockModal()">+ Register Walk-in Donation</button>
      </div>
      <div class="grid-4" id="stockGrid"></div>
    </div>

    <!-- Incoming Requests (OS Priority Queue) -->
    <div class="card">
      <div class="card-header">
        <div>
          <h2 class="card-title">📋 Incoming Blood Requests (OS Priority Queue)</h2>
          <p class="card-desc">Scheduled by Medical Urgency: Emergency requests are positioned at the top of the queue.</p>
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-blue btn-sm" onclick="switchNavSection('graph')">🌐 View Connectivity Graph</button>
          <button class="btn btn-secondary btn-sm" onclick="loadState()">↻ Refresh List</button>
        </div>
      </div>
      <div class="table-responsive">
        <table>
          <thead>
            <tr>
              <th>Queue Rank</th>
              <th>Request ID</th>
              <th>Patient Name</th>
              <th>Blood Group</th>
              <th>Units</th>
              <th>Urgency Priority</th>
              <th>Status</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="hospitalQueueRows"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ============================================================== VIEW 3: PATIENT PORTAL -->
  <div id="view-patient" class="hidden">
    <div class="grid-2">
      <!-- Blood Request Form -->
      <div class="card">
        <div class="card-header">
          <div>
            <h2 class="card-title">🩸 New Blood Transfusion Request</h2>
            <p class="card-desc">Submit your requirement to the nearest hospital blood bank.</p>
          </div>
        </div>
        <form onsubmit="handlePatientRequest(event)">
          <div class="form-group">
            <label>Patient ID / Name</label>
            <input type="text" id="patNameDisplay" disabled style="background:#f1f5f9;">
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label>Blood Group Needed</label>
              <select id="patBloodGroup" required></select>
            </div>
            <div class="form-group">
              <label>Hospital City</label>
              <select id="patCity" required></select>
            </div>
          </div>
          <div class="grid-2">
            <div class="form-group">
              <label>Units Needed</label>
              <input type="number" id="patUnits" value="2" min="1" max="10" required>
            </div>
            <div class="form-group">
              <label>Medical Urgency</label>
              <select id="patPriority" required>
                <option value="0">🚨 EMERGENCY (Accident / Acute)</option>
                <option value="1">⚠️ URGENT (Surgery / Dialysis)</option>
                <option value="2" selected>🩺 ROUTINE (Scheduled Transfusion)</option>
              </select>
            </div>
          </div>
          <button type="submit" class="btn btn-primary" style="width: 100%;">Submit Blood Request</button>
        </form>
      </div>

      <!-- Quick Donor Connectivity Summary Card (Clean & Visual) -->
      <div class="card" style="display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div class="card-header">
            <div>
              <h2 class="card-title">🌐 Connected Donor Network</h2>
              <p class="card-desc">Live social connection mapping with compatible voluntary donors.</p>
            </div>
          </div>
          <div style="font-size:13px; color:var(--slate); line-height:1.7;">
            <p>Our <b>Dynamic Link Prediction</b> engine analyzes the social network to connect your blood requirement with active eligible donors.</p>
            <div style="display:flex; gap:12px; margin-top:14px;">
              <div style="flex:1; background:#eff6ff; border:1px solid #bfdbfe; border-radius:10px; padding:12px; text-align:center;">
                <div style="font-size:20px;">🔵</div>
                <div style="font-size:13px; font-weight:700; color:#1d4ed8; margin-top:2px;">You (Patient)</div>
                <div style="font-size:11px; color:#60a5fa;">Blue Dot on Graph</div>
              </div>
              <div style="flex:1; background:#fef2f2; border:1px solid #fecaca; border-radius:10px; padding:12px; text-align:center;">
                <div style="font-size:20px;">🔴</div>
                <div style="font-size:13px; font-weight:700; color:#b91c1c; margin-top:2px;">Voluntary Donors</div>
                <div style="font-size:11px; color:#f87171;">Red Dots on Graph</div>
              </div>
            </div>
          </div>
        </div>
        <button class="btn btn-blue" style="width:100%; margin-top:16px;" onclick="switchNavSection('graph')">
          🌐 Open Interactive Connectivity Graph &rarr;
        </button>
      </div>
    </div>

    <!-- Patient My Requests Table -->
    <div class="card">
      <div class="card-header">
        <div>
          <h2 class="card-title">📜 My Transfusion Requests & Status</h2>
          <p class="card-desc">Personalized list of your blood requests (Isolated to your user account).</p>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="loadState()">↻ Refresh Status</button>
      </div>
      <div class="table-responsive">
        <table>
          <thead>
            <tr>
              <th>Request ID</th>
              <th>Blood Group</th>
              <th>City</th>
              <th>Units Needed</th>
              <th>Units Allocated</th>
              <th>Urgency</th>
              <th>Status</th>
              <th>Connected Donors</th>
            </tr>
          </thead>
          <tbody id="patientRequestsRows"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ============================================================== VIEW 4: VOLUNTARY DONOR PORTAL -->
  <div id="view-donor" class="hidden">
    <div class="grid-2">
      <!-- Donor Profile Card -->
      <div class="card">
        <div class="card-header">
          <div>
            <h2 class="card-title">💖 Voluntary Donor Profile</h2>
            <p class="card-desc">Your health and blood donation eligibility status.</p>
          </div>
        </div>
        <div style="font-size: 13px; color: var(--slate); line-height: 1.8;" id="donorProfileBox">
          <!-- Populated via JS -->
        </div>
        <div style="margin-top: 16px; display: flex; gap: 10px;">
          <button class="btn btn-rose" style="flex:1;" onclick="showDonorWalkinModal()">
            💖 Walk-in Donation at Hospital
          </button>
        </div>
      </div>

      <!-- Donor Connectivity Action Card -->
      <div class="card" style="display:flex; flex-direction:column; justify-content:space-between;">
        <div>
          <div class="card-header">
            <div>
              <h2 class="card-title">🌐 Your Social Donor Connectivity</h2>
              <p class="card-desc">Visual network showing patients you can save.</p>
            </div>
          </div>
          <div style="font-size:13px; color:var(--slate); line-height:1.7;">
            <p>You are represented as a <b>Red Dot (🔴)</b> in the connectivity network. Explore which patients (🔵 Blue Dots) are connected to your mutual social circle.</p>
            <div style="margin-top:12px; background:#f8fafc; border:1px solid var(--border); border-radius:8px; padding:10px 14px; font-size:12px;">
              <span>🩸 <b>Medical Compatibility:</b> Matching urgent appeals are shown in the table below.</span>
            </div>
          </div>
        </div>
        <button class="btn btn-blue" style="width:100%; margin-top:16px;" onclick="switchNavSection('graph')">
          🌐 View Network Connections on Graph &rarr;
        </button>
      </div>
    </div>

    <!-- Matching Patient Appeals Table -->
    <div class="card">
      <div class="card-header">
        <div>
          <h2 class="card-title">🚨 Urgent Blood Appeals Matching Your Blood Group</h2>
          <p class="card-desc">Patients in your city and network who require compatible blood.</p>
        </div>
        <button class="btn btn-secondary btn-sm" onclick="loadState()">↻ Refresh Appeals</button>
      </div>
      <div class="table-responsive">
        <table>
          <thead>
            <tr>
              <th>Request ID</th>
              <th>Patient Name</th>
              <th>Patient Blood Group</th>
              <th>Hospital City</th>
              <th>Units Needed</th>
              <th>Urgency</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody id="donorAppealsRows"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ============================================================== VIEW 5: ADMIN & AUDIT DASHBOARD -->
  <div id="view-admin" class="hidden">
    <div class="card">
      <div class="card-header">
        <div>
          <h2 class="card-title">📜 DBMS Live Audit Trail (User Activity Log)</h2>
          <p class="card-desc">Tracks authentication, requests, allocations, and administrative changes.</p>
        </div>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-blue btn-sm" onclick="switchNavSection('graph')">🌐 View Full Graph</button>
          <button class="btn btn-secondary btn-sm" onclick="loadAuditLogs()">↻ Refresh Audit Logs</button>
        </div>
      </div>
      <div class="table-responsive">
        <table>
          <thead>
            <tr>
              <th>Log ID</th>
              <th>Username</th>
              <th>Role</th>
              <th>Action</th>
              <th>Details</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody id="auditLogRows"></tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ============================================================== VIEW 6: VISUAL CONNECTIVITY GRAPH (FULL INTERACTIVE VIEW) -->
  <div id="view-graph-section" class="hidden">
    <div class="card" style="padding: 22px;">
      <div class="card-header" style="margin-bottom: 14px; flex-wrap: wrap; gap: 10px;">
        <div>
          <h2 class="card-title" style="font-size: 18px;">
            🌐 Live Donor & Patient Connectivity Graph (ML Link Prediction)
          </h2>
          <p class="card-desc">
            Visual graph representation: <b>Blue Dots (🔵)</b> represent Patients needing blood, <b>Red Dots (🔴)</b> represent Voluntary Donors, and lines represent topological & social connectivity.
          </p>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <select id="graphFilterSelect" onchange="filterGraphByPatient()" style="width: auto; min-width: 220px; padding: 6px 12px; font-size: 12px; font-weight:600;">
            <option value="ALL">Show All Patients & Donors</option>
          </select>
          <button class="btn btn-secondary btn-sm" onclick="initGraphNetwork(true)">↻ Re-layout</button>
          <button class="btn btn-primary btn-sm" onclick="switchNavSection('portal')">&larr; Back to Dashboard</button>
        </div>
      </div>

      <!-- Visual Legend Bar -->
      <div style="display:flex; align-items:center; gap:24px; background:#f8fafc; border:1px solid var(--border); padding:10px 16px; border-radius:10px; margin-bottom:14px; font-size:12px; font-weight:600; flex-wrap:wrap;">
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="display:inline-block; width:14px; height:14px; border-radius:50%; background:#3b82f6; box-shadow:0 0 8px rgba(59,130,246,0.8);"></span>
          <span><b>Blue Dot:</b> Patient (Blood Recipient)</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="display:inline-block; width:14px; height:14px; border-radius:50%; background:#ef4444; box-shadow:0 0 8px rgba(239,68,68,0.8);"></span>
          <span><b>Red Dot:</b> Voluntary Donor</span>
        </div>
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="display:inline-block; width:26px; height:3px; background:#94a3b8; border-radius:2px;"></span>
          <span><b>Connecting Line:</b> Social Link & ML Prediction Path</span>
        </div>
        <div style="margin-left:auto; color:var(--muted); font-size:11px;">
          💡 <i>Tip: Click & drag dots to rearrange &bull; Hover to inspect connection score</i>
        </div>
      </div>

      <!-- Canvas Container -->
      <div style="position:relative; width:100%; height:550px; background:#0f172a; border-radius:12px; overflow:hidden; border:1px solid #1e293b; box-shadow:inset 0 2px 10px rgba(0,0,0,0.5);">
        <canvas id="networkCanvas" style="width:100%; height:100%; display:block; cursor:grab;"></canvas>
        
        <!-- Floating Info Pill on Hover -->
        <div id="graphTooltip" style="position:absolute; bottom:16px; left:16px; right:16px; background:rgba(15, 23, 42, 0.94); border:1px solid #334155; backdrop-filter:blur(8px); border-radius:10px; padding:12px 18px; color:#f8fafc; font-size:13px; display:none; pointer-events:none; box-shadow:0 6px 18px rgba(0,0,0,0.5);">
          <div id="graphTooltipTitle" style="font-weight:700; margin-bottom:2px; font-size:14px;"></div>
          <div id="graphTooltipDesc" style="font-size:12px; color:#cbd5e1;"></div>
        </div>
      </div>
    </div>
  </div>

</div>

<!-- ============================================================== MODAL: REVIEW & SOLVE REQUEST (WITH LINK PREDICTION) -->
<div id="solveModal" class="modal-overlay hidden">
  <div class="modal-card">
    <div class="card-header" style="margin-bottom: 12px;">
      <h3 class="card-title" id="solveModalTitle">Review Blood Request</h3>
      <button class="btn btn-secondary btn-sm" onclick="closeSolveModal()">✕ Close</button>
    </div>

    <div id="solveAcceptorBox" class="card" style="background:#f8fafc; border:1px solid var(--border); margin-bottom:16px;">
      <!-- Populated via JS -->
    </div>

    <!-- Stock Check Banner -->
    <div id="solveStockStatus" style="margin-bottom: 18px;">
      <!-- Populated via JS -->
    </div>

    <!-- ML LINK PREDICTION SECTION -->
    <div id="solveLinkPredSection" class="hidden">
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
        <h4 style="font-size:14px; font-weight:700; color:var(--primary); display:flex; align-items:center; gap:6px;">
          🧠 Connected Donors Found (ML Dynamic Link Prediction)
        </h4>
        <span class="badge" style="background:#fef2f2; color:#991b1b; border:1px solid #fecaca;">Temporal Graph Active</span>
      </div>
      <p style="font-size:12px; color:var(--muted); margin-bottom:12px;">
        Link Prediction scanned the patient's dynamic social network to find eligible compatible donors with recent topological mutual connections:
      </p>
      <div id="solveDonorsContainer">
        <!-- Donor Cards Populated via JS -->
      </div>
    </div>

    <div style="display:flex; gap:10px; margin-top:20px; border-top:1px solid var(--border); padding-top:16px;">
      <button id="btnFulfillStock" class="btn btn-emerald" style="flex:1;" onclick="executeAllocation()">
        ⚡ Allocate from Blood Bank Storage
      </button>
      <button class="btn btn-secondary" onclick="closeSolveModal()">Cancel</button>
    </div>
  </div>
</div>

<!-- ============================================================== MODAL: ADD BLOOD DONATION (STAFF) -->
<div id="addStockModal" class="modal-overlay hidden">
  <div class="modal-card" style="max-width: 480px;">
    <div class="card-header" style="margin-bottom: 12px;">
      <h3 class="card-title">+ Register Blood Donation</h3>
      <button class="btn btn-secondary btn-sm" onclick="closeAddStockModal()">✕</button>
    </div>
    <form onsubmit="handleAddStock(event)">
      <div class="form-group">
        <label>Donor Full Name</label>
        <input type="text" id="addDonorName" placeholder="e.g. Rahul Sharma" value="Vikram Verma" required>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>Blood Group</label>
          <select id="addBloodGroup" required></select>
        </div>
        <div class="form-group">
          <label>Hospital Location</label>
          <select id="addHospitalCity">
            <option value="1">Doon Blood Bank (Dehradun)</option>
            <option value="2">City Blood Bank (Haridwar)</option>
            <option value="3">AIIMS Blood Bank (Rishikesh)</option>
            <option value="4">Civil Blood Bank (Roorkee)</option>
          </select>
        </div>
      </div>
      <div class="grid-2">
        <div class="form-group">
          <label>Number of Bags</label>
          <input type="number" id="addBagsCount" value="1" min="1" max="5" required>
        </div>
        <div class="form-group">
          <label>Expiry Date (35 Days Standard)</label>
          <input type="date" id="addExpiryDate" required>
        </div>
      </div>
      <div class="alert alert-info" style="font-size:12px; margin-bottom:14px;">
        Donor eligibility verified: Age &ge; 18, Hemoglobin &ge; 12.5 g/dL, 90-day cooldown enforced.
      </div>
      <div style="display:flex; gap:10px;">
        <button type="submit" class="btn btn-primary" style="flex:1;">Save to Blood Bank</button>
        <button type="button" class="btn btn-secondary" style="flex:1;" onclick="closeAddStockModal()">Cancel</button>
      </div>
    </form>
  </div>
</div>

<!-- ============================================================== MODAL: DONOR WALKIN DONATION -->
<div id="donorWalkinModal" class="modal-overlay hidden">
  <div class="modal-card" style="max-width: 440px;">
    <div class="card-header" style="margin-bottom: 12px;">
      <h3 class="card-title">💖 Complete Walk-in Blood Donation</h3>
      <button class="btn btn-secondary btn-sm" onclick="closeDonorWalkinModal()">✕</button>
    </div>
    <form onsubmit="handleDonorWalkinSubmit(event)">
      <div class="form-group">
        <label>Select Blood Bank</label>
        <select id="walkinHospital">
          <option value="1">Doon Blood Bank (Dehradun)</option>
          <option value="2">City Blood Bank (Haridwar)</option>
          <option value="3">AIIMS Blood Bank (Rishikesh)</option>
          <option value="4">Civil Blood Bank (Roorkee)</option>
        </select>
      </div>
      <div class="alert alert-success" style="font-size:12px;">
        Your blood unit will be safely registered into the hospital blood bank storage with 35-day standard shelf life.
      </div>
      <div style="display:flex; gap:10px;">
        <button type="submit" class="btn btn-rose" style="flex:1;">Confirm 1 Unit Donation</button>
        <button type="button" class="btn btn-secondary" style="flex:1;" onclick="closeDonorWalkinModal()">Cancel</button>
      </div>
    </form>
  </div>
</div>

<script>
  let currentUser = null;
  let currentActiveRequestId = null;
  let activeLoginRole = 'STAFF';
  let activeNavSection = 'portal'; // 'portal' or 'graph'
  const GROUPS = ['A+','A-','B+','B-','AB+','AB-','O+','O-'];
  const CITIES = ['Dehradun','Haridwar','Rishikesh','Roorkee','Haldwani'];

  function initSelectors() {
    const sPat = document.getElementById('patBloodGroup');
    const sAdd = document.getElementById('addBloodGroup');
    const sReg = document.getElementById('regBloodGroup');
    GROUPS.forEach(g => {
      sPat.add(new Option(g, g));
      sAdd.add(new Option(g, g));
      sReg.add(new Option(g, g));
    });

    const cPat = document.getElementById('patCity');
    const cReg = document.getElementById('regCity');
    CITIES.forEach(c => {
      cPat.add(new Option(c, c));
      cReg.add(new Option(c, c));
    });

    const exp = new Date();
    exp.setDate(exp.getDate() + 35);
    document.getElementById('addExpiryDate').value = exp.toISOString().split('T')[0];
  }

  function showToast(msg, type='info') {
    const t = document.getElementById('toast');
    t.className = 'alert alert-' + type;
    t.textContent = msg;
    t.classList.remove('hidden');
    setTimeout(() => t.classList.add('hidden'), 5000);
  }

  function setAuthMode(mode) {
    const btnL = document.getElementById('btnModeLogin');
    const btnR = document.getElementById('btnModeRegister');
    const fL = document.getElementById('authLoginForm');
    const fR = document.getElementById('authRegisterForm');

    if (mode === 'login') {
      btnL.classList.add('active');
      btnR.classList.remove('active');
      fL.classList.remove('hidden');
      fR.classList.add('hidden');
    } else {
      btnR.classList.add('active');
      btnL.classList.remove('active');
      fR.classList.remove('hidden');
      fL.classList.add('hidden');
    }
  }

  function switchLoginRole(role) {
    activeLoginRole = role;
    document.getElementById('tabStaffAuth').classList.toggle('active', role === 'STAFF');
    document.getElementById('tabPatientAuth').classList.toggle('active', role === 'USER');
    document.getElementById('tabDonorAuth').classList.toggle('active', role === 'DONOR');
    document.getElementById('tabAdminAuth').classList.toggle('active', role === 'ADMIN');

    if (role === 'STAFF') {
      document.getElementById('inputUsername').value = 'staff';
      document.getElementById('inputPassword').value = 'staff123';
    } else if (role === 'USER') {
      document.getElementById('inputUsername').value = 'rahul';
      document.getElementById('inputPassword').value = 'user123';
    } else if (role === 'DONOR') {
      document.getElementById('inputUsername').value = 'vikram';
      document.getElementById('inputPassword').value = 'donor123';
    } else if (role === 'ADMIN') {
      document.getElementById('inputUsername').value = 'admin';
      document.getElementById('inputPassword').value = 'admin123';
    }
  }

  function fillCreds(u, p, role) {
    setAuthMode('login');
    switchLoginRole(role);
    document.getElementById('inputUsername').value = u;
    document.getElementById('inputPassword').value = p;
  }

  function toggleRegFields() {
    const role = document.getElementById('regRole').value;
    const med = document.getElementById('regMedicalFields');
    if (role === 'STAFF') {
      med.classList.add('hidden');
    } else {
      med.classList.remove('hidden');
    }
  }

  function switchNavSection(section) {
    activeNavSection = section;
    document.getElementById('btnNavPortal').classList.toggle('active', section === 'portal');
    document.getElementById('btnNavGraph').classList.toggle('active', section === 'graph');

    const vGraph = document.getElementById('view-graph-section');
    if (section === 'graph') {
      vGraph.classList.remove('hidden');
      document.getElementById('view-hospital').classList.add('hidden');
      document.getElementById('view-patient').classList.add('hidden');
      document.getElementById('view-donor').classList.add('hidden');
      document.getElementById('view-admin').classList.add('hidden');
      initGraphNetwork();
    } else {
      vGraph.classList.add('hidden');
      renderView();
    }
  }

  async function api(path, data=null, method='GET') {
    const opts = { method: data ? 'POST' : method, headers: {} };
    if (data) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(data);
    }
    const res = await fetch(path, opts);
    const json = await res.json();
    if (!res.ok) throw new Error(json.error || 'Server error');
    return json;
  }

  async function checkAuth() {
    try {
      const res = await api('/api/me');
      currentUser = res.user;
    } catch {
      currentUser = null;
    }
    renderView();
    if (currentUser) loadState();
  }

  function renderView() {
    const vLogin = document.getElementById('view-login');
    const vHosp = document.getElementById('view-hospital');
    const vPat = document.getElementById('view-patient');
    const vDonor = document.getElementById('view-donor');
    const vAdmin = document.getElementById('view-admin');
    const vGraph = document.getElementById('view-graph-section');
    const uInfo = document.getElementById('userInfo');
    const nTabs = document.getElementById('navTabs');

    if (!currentUser) {
      vLogin.classList.remove('hidden');
      vHosp.classList.add('hidden');
      vPat.classList.add('hidden');
      vDonor.classList.add('hidden');
      vAdmin.classList.add('hidden');
      vGraph.classList.add('hidden');
      uInfo.classList.add('hidden');
      nTabs.classList.add('hidden');
      return;
    }

    vLogin.classList.add('hidden');
    uInfo.classList.remove('hidden');
    nTabs.classList.remove('hidden');
    
    // User display in navbar
    const profName = currentUser.profile ? currentUser.profile.name : currentUser.username;
    const profSub = currentUser.profile ? `${currentUser.profile.blood_group} &bull; ${currentUser.profile.city}` : currentUser.username;
    document.getElementById('userDisplay').textContent = profName;
    document.getElementById('userSubDisplay').innerHTML = profSub;

    const b = document.getElementById('roleBadge');
    b.textContent = currentUser.role === 'USER' ? 'PATIENT' : currentUser.role;
    b.className = 'badge badge-' + currentUser.role.toLowerCase();

    // If graph is currently open, stay on graph
    if (activeNavSection === 'graph') {
      vGraph.classList.remove('hidden');
      vHosp.classList.add('hidden');
      vPat.classList.add('hidden');
      vDonor.classList.add('hidden');
      vAdmin.classList.add('hidden');
      return;
    }

    vGraph.classList.add('hidden');
    vHosp.classList.add('hidden');
    vPat.classList.add('hidden');
    vDonor.classList.add('hidden');
    vAdmin.classList.add('hidden');

    if (currentUser.role === 'STAFF') {
      vHosp.classList.remove('hidden');
    } else if (currentUser.role === 'USER') {
      vPat.classList.remove('hidden');
      document.getElementById('patNameDisplay').value = `${profName} (Patient #${currentUser.person_id || 'Self'})`;
      if (currentUser.profile && currentUser.profile.blood_group) {
        document.getElementById('patBloodGroup').value = currentUser.profile.blood_group;
      }
      if (currentUser.profile && currentUser.profile.city) {
        document.getElementById('patCity').value = currentUser.profile.city;
      }
    } else if (currentUser.role === 'DONOR') {
      vDonor.classList.remove('hidden');
      renderDonorProfile();
    } else if (currentUser.role === 'ADMIN') {
      vHosp.classList.remove('hidden');
      vAdmin.classList.remove('hidden');
      loadAuditLogs();
    }
  }

  function renderDonorProfile() {
    const prof = currentUser.profile || {};
    const age = prof.birth_year ? (2026 - prof.birth_year) : 25;
    const lastDon = prof.last_donation ? prof.last_donation : 'None recorded';
    const bg = prof.blood_group || 'O+';
    const city = prof.city || 'Dehradun';

    document.getElementById('donorProfileBox').innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); padding-bottom:8px; margin-bottom:8px;">
        <span style="font-size:15px; font-weight:700;">${prof.name || currentUser.username}</span>
        <span class="badge badge-donor">VOLUNTARY DONOR</span>
      </div>
      <div>Blood Group: <b style="color:var(--primary); font-size:14px;">${bg}</b></div>
      <div>Registered City: <b>${city}</b></div>
      <div>Age: <b>${age} years</b> (Medical criteria &ge; 18 passed)</div>
      <div>Last Donation: <b>${lastDon}</b></div>
      <div style="margin-top:6px;">
        <span class="badge" style="background:#ecfdf5; color:#047857; border:1px solid #a7f3d0;">
          ✔ Eligible to Donate (90-day cooldown satisfied)
        </span>
      </div>
    `;
  }

  async function handleAuthSubmit(e) {
    e.preventDefault();
    const u = document.getElementById('inputUsername').value;
    const p = document.getElementById('inputPassword').value;
    try {
      const res = await api('/api/login', { username: u, password: p });
      currentUser = res.user;
      showToast(`Welcome back, ${currentUser.username}!`, 'success');
      activeNavSection = 'portal';
      renderView();
      loadState();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  async function handleRegisterSubmit(e) {
    e.preventDefault();
    const payload = {
      name: document.getElementById('regName').value,
      username: document.getElementById('regUsername').value,
      password: document.getElementById('regPassword').value,
      role: document.getElementById('regRole').value,
      blood_group: document.getElementById('regBloodGroup').value,
      city: document.getElementById('regCity').value,
      age: parseInt(document.getElementById('regAge').value)
    };
    try {
      const res = await api('/api/register', payload);
      currentUser = res.user;
      showToast(`Account successfully registered! Welcome, ${currentUser.username}.`, 'success');
      activeNavSection = 'portal';
      renderView();
      loadState();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  async function logout() {
    await api('/api/logout', {});
    currentUser = null;
    activeNavSection = 'portal';
    showToast('Signed out successfully.', 'info');
    renderView();
  }

  async function handlePatientRequest(e) {
    e.preventDefault();
    const payload = {
      requester_id: currentUser && currentUser.person_id ? currentUser.person_id : 10,
      blood_group: document.getElementById('patBloodGroup').value,
      city: document.getElementById('patCity').value,
      units: parseInt(document.getElementById('patUnits').value),
      priority: parseInt(document.getElementById('patPriority').value)
    };
    try {
      const res = await api('/api/request', payload);
      showToast(`Blood Request #${res.request_id} submitted to Hospital (Queue Priority: ${payload.priority})!`, 'success');
      loadState();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  // Hospital Inspect & Solve Request (with ML Link Prediction)
  async function inspectRequest(rid) {
    currentActiveRequestId = rid;
    try {
      const res = await api(`/api/inspect_request?request_id=${rid}`);
      document.getElementById('solveModalTitle').textContent = `Review Request #${rid}`;
      
      const req = res.request;
      const pBadge = req.priority === 0 ? 'badge-prio-0' : (req.priority === 1 ? 'badge-prio-1' : 'badge-prio-2');
      const pText = req.priority === 0 ? '🚨 EMERGENCY (Accident / Acute)' : (req.priority === 1 ? '⚠️ URGENT' : '🩺 ROUTINE');

      document.getElementById('solveAcceptorBox').innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div>
            <div style="font-size:15px; font-weight:700; color:var(--dark);">Acceptor: ${req.requester_name}</div>
            <div style="font-size:12px; color:var(--muted);">Location: ${req.city} | Age: ${req.age} yrs | Patient ID: #${req.requester_id}</div>
          </div>
          <span class="badge ${pBadge}">${pText}</span>
        </div>
        <div style="display:flex; gap:18px; margin-top:12px; font-size:13px; color:var(--slate);">
          <div>Blood Group Needed: <b>${req.blood_group}</b></div>
          <div>Units Required: <b>${req.units_needed} units</b></div>
          <div>Already Allocated: <b>${req.units_allocated} units</b></div>
        </div>
      `;

      const stockStatus = document.getElementById('solveStockStatus');
      const stockAvailable = res.stock_available;
      if (stockAvailable >= req.units_needed) {
        stockStatus.innerHTML = `
          <div class="alert alert-success" style="margin-bottom:0;">
            ✔ <b>Storage Match:</b> Blood bank has <b>${stockAvailable} units</b> of compatible blood available in storage!
          </div>
        `;
        document.getElementById('btnFulfillStock').classList.remove('hidden');
      } else {
        stockStatus.innerHTML = `
          <div class="alert alert-warning" style="margin-bottom:0;">
            ⚠️ <b>Stock Shortage:</b> Only <b>${stockAvailable} units</b> in storage (Need ${req.units_needed} units). 
            Dynamic Link Prediction has scanned the patient's social network below!
          </div>
        `;
      }

      // Render ML Link Prediction Donors
      const lpSection = document.getElementById('solveLinkPredSection');
      const donorsContainer = document.getElementById('solveDonorsContainer');
      donorsContainer.innerHTML = '';
      
      if (res.donors && res.donors.length > 0) {
        lpSection.classList.remove('hidden');
        res.donors.forEach((d, i) => {
          const div = document.createElement('div');
          div.style = 'border: 1px solid var(--border); border-radius: 10px; padding: 12px; margin-bottom: 10px; background: #fff;';
          div.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <div>
                <b>#${i + 1} ${d.name}</b> (Donor ID: #${d.donor_id}) &bull; Blood Group: <b style="color:var(--primary);">${d.blood_group}</b> &bull; Age: ${d.age} yrs
              </div>
              <span class="badge" style="background:#fee2e2; color:#991b1b; border:1px solid #fca5a5;">
                Link Affinity: ${d.score.toFixed(4)}
              </span>
            </div>
            <div class="network-path">
              <span>🌐</span>
              <span><b>Connection Network:</b> ${d.connection_path}</span>
            </div>
            <div style="display:flex; justify-content:space-between; align-items:center; margin-top:8px;">
              <span style="font-size:11px; color:var(--muted);">Last active in social graph: ${d.last_seen_months} months ago &bull; 90-day cooldown verified</span>
              <button class="btn btn-primary btn-sm" onclick="sendDonorCall('${d.name}', '${d.donor_id}')">📞 Dispatch Urgent Call</button>
            </div>
          `;
          donorsContainer.appendChild(div);
        });
      } else {
        lpSection.classList.add('hidden');
      }

      document.getElementById('solveModal').classList.remove('hidden');
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  function closeSolveModal() { document.getElementById('solveModal').classList.add('hidden'); }
  function sendDonorCall(donorName, donorId) { showToast(`Urgent blood appeal dispatched to ${donorName} (Donor #${donorId})!`, 'success'); }

  async function executeAllocation() {
    if (!currentActiveRequestId) return;
    try {
      const res = await api('/api/process', { request_id: currentActiveRequestId });
      closeSolveModal();
      showToast(`Request #${res.request_id} allocated ${res.allocated_now} units (Status: ${res.status})!`, 'success');
      loadState();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  function showAddStockModal() { document.getElementById('addStockModal').classList.remove('hidden'); }
  function closeAddStockModal() { document.getElementById('addStockModal').classList.add('hidden'); }

  async function handleAddStock(e) {
    e.preventDefault();
    const payload = {
      hospital_id: parseInt(document.getElementById('addHospitalCity').value),
      blood_group: document.getElementById('addBloodGroup').value,
      expiry_date: document.getElementById('addExpiryDate').value,
      bags: parseInt(document.getElementById('addBagsCount').value),
      donor_name: document.getElementById('addDonorName').value
    };
    try {
      await api('/api/inventory/add', payload);
      closeAddStockModal();
      showToast(`${payload.bags} blood bag(s) successfully added to storage inventory!`, 'success');
      loadState();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  function showDonorWalkinModal() { document.getElementById('donorWalkinModal').classList.remove('hidden'); }
  function closeDonorWalkinModal() { document.getElementById('donorWalkinModal').classList.add('hidden'); }

  async function handleDonorWalkinSubmit(e) {
    e.preventDefault();
    const hid = parseInt(document.getElementById('walkinHospital').value);
    try {
      const res = await api('/api/donor/walkin_donate', { hospital_id: hid });
      closeDonorWalkinModal();
      showToast(res.message, 'success');
      loadState();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  async function pledgeForRequest(rid) {
    try {
      const res = await api('/api/donor/pledge', { request_id: rid });
      showToast(res.message, 'success');
      loadState();
    } catch (err) {
      showToast(err.message, 'danger');
    }
  }

  async function loadAuditLogs() {
    try {
      const res = await api('/api/audit_logs');
      const tbody = document.getElementById('auditLogRows');
      tbody.innerHTML = '';
      res.logs.forEach(l => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
          <td>#${l.log_id}</td>
          <td><b>${l.username}</b></td>
          <td><span class="badge badge-${l.role.toLowerCase()}">${l.role}</span></td>
          <td><b>${l.action}</b></td>
          <td>${l.details}</td>
          <td>t=${l.created_at}</td>
        `;
        tbody.appendChild(tr);
      });
    } catch (err) {
      console.error(err);
    }
  }

  async function loadState() {
    try {
      const s = await api('/api/state');

      // 1. Stock Grid (Staff & Admin)
      const sg = document.getElementById('stockGrid');
      if (sg) {
        sg.innerHTML = '';
        for (const [bg, count] of Object.entries(s.inventory)) {
          const div = document.createElement('div');
          div.className = 'stock-box';
          div.innerHTML = `
            <div class="stock-group">${bg}</div>
            <div class="stock-count" style="color:${count > 0 ? 'var(--primary)' : 'var(--muted)'};">${count}</div>
            <div class="stock-label">${count > 0 ? 'Units Ready' : 'Empty'}</div>
          `;
          sg.appendChild(div);
        }
      }

      // 2. Hospital Priority Queue (Emergency at top)
      const hq = document.getElementById('hospitalQueueRows');
      if (hq) {
        hq.innerHTML = '';
        if (!s.queue || s.queue.length === 0) {
          hq.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--muted); padding:20px;">No pending requests in queue.</td></tr>';
        } else {
          s.queue.forEach((q, idx) => {
            const tr = document.createElement('tr');
            const pBadge = q.priority === 0 ? 'badge-prio-0' : (q.priority === 1 ? 'badge-prio-1' : 'badge-prio-2');
            const pText = q.priority === 0 ? '🚨 EMERGENCY' : (q.priority === 1 ? '⚠️ URGENT' : '🩺 ROUTINE');
            tr.innerHTML = `
              <td><b>#${idx + 1}</b></td>
              <td>#${q.request_id}</td>
              <td><b>${q.requester_name || 'Patient'}</b></td>
              <td><b style="color:var(--primary);">${q.blood_group}</b> (${q.city})</td>
              <td><b>${q.units_needed}</b> units</td>
              <td><span class="badge ${pBadge}">${pText}</span></td>
              <td><span class="badge badge-status-PENDING">PENDING</span></td>
              <td>
                <button class="btn btn-emerald btn-sm" onclick="inspectRequest(${q.request_id})">
                  Review & Fulfill &rarr;
                </button>
              </td>
            `;
            hq.appendChild(tr);
          });
        }
      }

      // 3. Patient Requests Table (Filtered specifically to this patient)
      const pr = document.getElementById('patientRequestsRows');
      if (pr) {
        pr.innerHTML = '';
        let myReqs = s.requests;
        if (currentUser && currentUser.role === 'USER' && currentUser.person_id) {
          myReqs = s.requests.filter(r => r.requester_id === currentUser.person_id);
        }
        if (myReqs.length === 0) {
          pr.innerHTML = '<tr><td colspan="8" style="text-align:center; color:var(--muted); padding:20px;">No blood requests submitted yet. Use the form above to submit your first request.</td></tr>';
        } else {
          myReqs.forEach(r => {
            const tr = document.createElement('tr');
            const pBadge = r.priority === 0 ? 'badge-prio-0' : (r.priority === 1 ? 'badge-prio-1' : 'badge-prio-2');
            const pText = r.priority === 0 ? 'EMERGENCY' : (r.priority === 1 ? 'URGENT' : 'ROUTINE');
            tr.innerHTML = `
              <td><b>#${r.request_id}</b></td>
              <td><b>${r.blood_group}</b></td>
              <td>${r.city}</td>
              <td>${r.units_needed} units</td>
              <td><b>${r.units_allocated}</b> units</td>
              <td><span class="badge ${pBadge}">${pText}</span></td>
              <td><span class="badge badge-status-${r.status}">${r.status}</span></td>
              <td>
                <button class="btn btn-secondary btn-sm" onclick="inspectRequest(${r.request_id})">
                  🔍 View Connected Donors
                </button>
              </td>
            `;
            pr.appendChild(tr);
          });
        }
      }

      // 4. Voluntary Donor Appeals Table
      const da = document.getElementById('donorAppealsRows');
      if (da && s.donor_appeals) {
        da.innerHTML = '';
        if (s.donor_appeals.length === 0) {
          da.innerHTML = '<tr><td colspan="7" style="text-align:center; color:var(--muted); padding:20px;">No pending urgent appeals matching your blood group right now. Thank you for being ready!</td></tr>';
        } else {
          s.donor_appeals.forEach(ap => {
            const tr = document.createElement('tr');
            const pBadge = ap.priority === 0 ? 'badge-prio-0' : (ap.priority === 1 ? 'badge-prio-1' : 'badge-prio-2');
            const pText = ap.priority === 0 ? '🚨 EMERGENCY' : (ap.priority === 1 ? '⚠️ URGENT' : '🩺 ROUTINE');
            tr.innerHTML = `
              <td><b>#${ap.request_id}</b></td>
              <td><b>${ap.requester_name}</b></td>
              <td><b style="color:var(--primary);">${ap.blood_group}</b></td>
              <td>${ap.city}</td>
              <td><b>${ap.units_needed}</b> units</td>
              <td><span class="badge ${pBadge}">${pText}</span></td>
              <td>
                <button class="btn btn-rose btn-sm" onclick="pledgeForRequest(${ap.request_id})">
                  🤝 Pledge Blood &rarr;
                </button>
              </td>
            `;
            da.appendChild(tr);
          });
        }
      }

    } catch (err) {
      console.error(err);
    }
  }

  // ============================================================================
  // INTERACTIVE GRAPH ENGINE: HTML5 CANVAS (Zero Dependencies)
  // Blue Dots = Patients (🔵), Red Dots = Voluntary Donors (🔴), Lines = Connections
  // ============================================================================
  let graphData = { nodes: [], edges: [] };
  let graphAnimId = null;
  let hoveredNode = null;
  let hoveredEdge = null;
  let draggedNode = null;
  let selectedPatientId = 'ALL';

  async function initGraphNetwork(forceReset=false) {
    try {
      const res = await api('/api/graph_network');
      graphData = res;

      // Populate filter dropdown
      const sel = document.getElementById('graphFilterSelect');
      sel.innerHTML = '<option value="ALL">Show All Patients & Donors</option>';
      const patients = graphData.nodes.filter(n => n.type === 'patient');
      patients.forEach(p => {
        sel.add(new Option(`Patient: ${p.name} (${p.blood_group} - ${p.city})`, p.id));
      });
      if (selectedPatientId !== 'ALL') {
        sel.value = selectedPatientId;
      }

      setupCanvasPhysics(forceReset);
    } catch (err) {
      console.error('Failed to load graph network:', err);
    }
  }

  function filterGraphByPatient() {
    selectedPatientId = document.getElementById('graphFilterSelect').value;
  }

  function setupCanvasPhysics(forceReset=false) {
    const canvas = document.getElementById('networkCanvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    // Resize canvas
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    // Node positioning
    const nodeMap = {};
    const totalNodes = graphData.nodes.length;
    graphData.nodes.forEach((n, i) => {
      if (forceReset || n.x === undefined) {
        // Arrange patients on left-center, donors on right-center or radially
        const angle = (i / totalNodes) * Math.PI * 2;
        const radius = Math.min(w, h) * (n.type === 'patient' ? 0.28 : 0.42);
        n.x = (w / 2) + Math.cos(angle) * radius + (Math.random() - 0.5) * 40;
        n.y = (h / 2) + Math.sin(angle) * radius + (Math.random() - 0.5) * 40;
        n.vx = 0;
        n.vy = 0;
      }
      n.radius = n.type === 'patient' ? 14 : 11;
      nodeMap[n.id] = n;
    });

    // Resolve edge objects
    const resolvedEdges = [];
    graphData.edges.forEach(e => {
      const s = nodeMap[e.source];
      const t = nodeMap[e.target];
      if (s && t) {
        resolvedEdges.push({ ...e, sourceNode: s, targetNode: t });
      }
    });

    // Mouse interactions
    let mouseX = 0, mouseY = 0;
    let isDragging = false;

    canvas.onmousedown = (e) => {
      const r = canvas.getBoundingClientRect();
      mouseX = e.clientX - r.left;
      mouseY = e.clientY - r.top;
      for (const n of graphData.nodes) {
        const dx = n.x - mouseX;
        const dy = n.y - mouseY;
        if (Math.sqrt(dx * dx + dy * dy) <= n.radius + 6) {
          draggedNode = n;
          isDragging = true;
          canvas.style.cursor = 'grabbing';
          break;
        }
      }
    };

    window.onmousemove = (e) => {
      const r = canvas.getBoundingClientRect();
      mouseX = e.clientX - r.left;
      mouseY = e.clientY - r.top;
      if (isDragging && draggedNode) {
        draggedNode.x = Math.max(20, Math.min(w - 20, mouseX));
        draggedNode.y = Math.max(20, Math.min(h - 20, mouseY));
        draggedNode.vx = 0;
        draggedNode.vy = 0;
      } else {
        // Hover detection
        hoveredNode = null;
        for (const n of graphData.nodes) {
          const dx = n.x - mouseX;
          const dy = n.y - mouseY;
          if (Math.sqrt(dx * dx + dy * dy) <= n.radius + 6) {
            hoveredNode = n;
            break;
          }
        }
        updateGraphTooltip(hoveredNode, mouseX, mouseY);
      }
    };

    window.onmouseup = () => {
      isDragging = false;
      draggedNode = null;
      canvas.style.cursor = 'grab';
    };

    // Physics Animation Loop
    if (graphAnimId) cancelAnimationFrame(graphAnimId);

    function step() {
      // 1. Physics force simulation
      const k = 90;
      const nodes = graphData.nodes;

      // Repulsion between all nodes
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const n1 = nodes[i];
          const n2 = nodes[j];
          let dx = n2.x - n1.x;
          let dy = n2.y - n1.y;
          let dist = Math.sqrt(dx * dx + dy * dy) || 1;
          if (dist < 260) {
            const force = (k * k) / (dist * dist);
            const fx = (dx / dist) * force * 0.45;
            const fy = (dy / dist) * force * 0.45;
            if (n1 !== draggedNode) { n1.vx -= fx; n1.vy -= fy; }
            if (n2 !== draggedNode) { n2.vx += fx; n2.vy += fy; }
          }
        }
      }

      // Spring attraction along edges
      for (const e of resolvedEdges) {
        const n1 = e.sourceNode;
        const n2 = e.targetNode;
        let dx = n2.x - n1.x;
        let dy = n2.y - n1.y;
        let dist = Math.sqrt(dx * dx + dy * dy) || 1;
        const ideal = 130;
        const force = (dist - ideal) * 0.0035;
        const fx = (dx / dist) * force;
        const fy = (dy / dist) * force;
        if (n1 !== draggedNode) { n1.vx += fx; n1.vy += fy; }
        if (n2 !== draggedNode) { n2.vx -= fx; n2.vy -= fy; }
      }

      // Gravitational center pull
      const cx = w / 2;
      const cy = h / 2;
      for (const n of nodes) {
        if (n !== draggedNode) {
          n.vx += (cx - n.x) * 0.0015;
          n.vy += (cy - n.y) * 0.0015;

          // Apply velocity with damping
          n.x += n.vx;
          n.y += n.vy;
          n.vx *= 0.82;
          n.vy *= 0.82;

          // Boundary constraints
          n.x = Math.max(30, Math.min(w - 30, n.x));
          n.y = Math.max(30, Math.min(h - 30, n.y));
        }
      }

      // 2. Draw Frame
      ctx.clearRect(0, 0, w, h);

      // Subtle background grid
      ctx.fillStyle = '#0f172a';
      ctx.fillRect(0, 0, w, h);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.03)';
      ctx.lineWidth = 1;
      for (let x = 0; x < w; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke(); }
      for (let y = 0; y < h; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke(); }

      // Determine active highlight set
      let activeNodeIds = new Set();
      if (selectedPatientId !== 'ALL') {
        activeNodeIds.add(selectedPatientId);
        resolvedEdges.forEach(e => {
          if (e.sourceNode.id === selectedPatientId) activeNodeIds.add(e.targetNode.id);
        });
      } else if (hoveredNode) {
        activeNodeIds.add(hoveredNode.id);
        resolvedEdges.forEach(e => {
          if (e.sourceNode.id === hoveredNode.id) activeNodeIds.add(e.targetNode.id);
          if (e.targetNode.id === hoveredNode.id) activeNodeIds.add(e.sourceNode.id);
        });
      }

      // Draw Edges
      for (const e of resolvedEdges) {
        const s = e.sourceNode;
        const t = e.targetNode;
        const isHighlighted = (activeNodeIds.size > 0) && activeNodeIds.has(s.id) && activeNodeIds.has(t.id);
        const isDimmed = (activeNodeIds.size > 0) && !isHighlighted;

        ctx.beginPath();
        ctx.moveTo(s.x, s.y);
        ctx.lineTo(t.x, t.y);

        if (isHighlighted) {
          ctx.strokeStyle = '#f43f5e';
          ctx.lineWidth = 2.8;
          ctx.shadowColor = 'rgba(244, 63, 94, 0.8)';
          ctx.shadowBlur = 10;
        } else if (isDimmed) {
          ctx.strokeStyle = 'rgba(148, 163, 184, 0.1)';
          ctx.lineWidth = 1;
          ctx.shadowBlur = 0;
        } else {
          ctx.strokeStyle = 'rgba(148, 163, 184, 0.35)';
          ctx.lineWidth = 1.4;
          ctx.shadowBlur = 0;
        }
        ctx.stroke();
        ctx.shadowBlur = 0; // reset
      }

      // Draw Nodes
      for (const n of nodes) {
        const isHighlighted = (activeNodeIds.size === 0) || activeNodeIds.has(n.id);
        const isDimmed = !isHighlighted;
        const alpha = isDimmed ? 0.25 : 1.0;

        ctx.save();
        ctx.globalAlpha = alpha;

        // Outer glow
        const isPatient = n.type === 'patient';
        const baseColor = isPatient ? '#3b82f6' : '#ef4444'; // Blue Dot vs Red Dot
        const glowColor = isPatient ? 'rgba(59, 130, 246, 0.5)' : 'rgba(239, 68, 68, 0.5)';

        if (!isDimmed) {
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.radius + 5, 0, Math.PI * 2);
          ctx.fillStyle = glowColor;
          ctx.fill();
        }

        // Inner Circle
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.radius, 0, Math.PI * 2);
        const grad = ctx.createRadialGradient(n.x - 3, n.y - 3, 2, n.x, n.y, n.radius);
        if (isPatient) {
          grad.addColorStop(0, '#93c5fd');
          grad.addColorStop(1, '#2563eb');
        } else {
          grad.addColorStop(0, '#fca5a5');
          grad.addColorStop(1, '#dc2626');
        }
        ctx.fillStyle = grad;
        ctx.fill();

        ctx.lineWidth = 2;
        ctx.strokeStyle = isHighlighted ? '#ffffff' : (isPatient ? '#1d4ed8' : '#b91c1c');
        ctx.stroke();

        // Node Label
        ctx.font = '11px -apple-system, sans-serif';
        ctx.fillStyle = isDimmed ? 'rgba(203, 213, 225, 0.3)' : '#f8fafc';
        ctx.textAlign = 'center';
        ctx.fillText(n.label, n.x, n.y + n.radius + 14);

        ctx.restore();
      }

      graphAnimId = requestAnimationFrame(step);
    }

    step();
  }

  function updateGraphTooltip(node, x, y) {
    const tip = document.getElementById('graphTooltip');
    const title = document.getElementById('graphTooltipTitle');
    const desc = document.getElementById('graphTooltipDesc');

    if (!node) {
      tip.style.display = 'none';
      return;
    }

    tip.style.display = 'block';
    if (node.type === 'patient') {
      title.innerHTML = `🔵 <b style="color:#60a5fa;">PATIENT (Blood Recipient):</b> ${node.name} &bull; Blood Group Needed: <b style="color:#ef4444;">${node.blood_group}</b>`;
      desc.innerHTML = `Location: <b>${node.city}</b> &bull; Priority: <b>${node.priority === 0 ? '🚨 EMERGENCY' : (node.priority === 1 ? '⚠️ URGENT' : '🩺 ROUTINE')}</b> &bull; Units Needed: <b>${node.units || 2} unit(s)</b>`;
    } else {
      title.innerHTML = `🔴 <b style="color:#f87171;">VOLUNTARY DONOR:</b> ${node.name} &bull; Blood Group: <b style="color:#ef4444;">${node.blood_group}</b>`;
      desc.innerHTML = `Location: <b>${node.city}</b> &bull; Age: <b>${node.age} yrs</b> &bull; Status: <span style="color:#34d399; font-weight:700;">✔ Available & Eligible to Donate</span>`;
    }
  }

  initSelectors();
  checkAuth();
</script>
</body>
</html>
"""


# ==============================================================================
# REST API ENDPOINTS
# ==============================================================================
@app.route("/")
def index():
    return HTML_TEMPLATE


@app.route("/api/me")
def api_me():
    if "user" not in session:
        return jsonify({"user": None}), 401
    return jsonify({"user": session["user"]})


@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    password = data.get("password", "")
    db = _db()
    try:
        user = db.verify_user(username, password)
        if not user:
            return jsonify({"error": "Invalid username or password"}), 401
        session["user"] = user
        db.log_audit(user["username"], user["role"], "LOGIN", "User logged in", STATE["clock"])
        return jsonify({"message": "Login successful", "user": user})
    finally:
        db.close()


@app.route("/api/logout", methods=["POST"])
def api_logout():
    user = session.pop("user", None)
    if user:
        db = _db()
        try:
            db.log_audit(user["username"], user["role"], "LOGOUT", "User logged out", STATE["clock"])
        finally:
            db.close()
    return jsonify({"message": "Logged out"})


@app.route("/api/register", methods=["POST"])
def api_register():
    data = request.get_json() or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    role = data.get("role", "USER")
    if role not in ("ADMIN", "STAFF", "USER", "DONOR"):
        return jsonify({"error": "Invalid role specified"}), 400
    if not username or not password:
        return jsonify({"error": "Username and password required"}), 400

    db = _db()
    try:
        if db._run(f"SELECT 1 FROM users WHERE username={db.ph}", (username,)):
            return jsonify({"error": "Username already exists"}), 400

        person_id = None
        profile_info = None
        if role in ("USER", "DONOR"):
            name = data.get("name", username.capitalize())
            bg = data.get("blood_group", "O+")
            city = data.get("city", "Dehradun")
            age = int(data.get("age", 25))
            birth_year = TODAY.year - age
            last_don = "2026-05-10" if role == "DONOR" else None
            person_id = db.add_person(name, bg, city, birth_year, last_donation=last_don, available=1)
            profile_info = {
                "name": name,
                "blood_group": bg,
                "city": city,
                "birth_year": birth_year,
                "last_donation": last_don,
                "available": 1
            }

        uid = db.register_user(username, password, role=role, person_id=person_id, created_at=STATE["clock"])
        user = {"user_id": uid, "username": username, "role": role, "person_id": person_id, "profile": profile_info}
        session["user"] = user
        db.log_audit(username, role, "REGISTER", f"Account created with role {role} (Name: {data.get('name', username)})", STATE["clock"])
        return jsonify({"message": "Registration successful", "user": user})
    finally:
        db.close()


@app.route("/api/state")
def api_state():
    db = _db()
    try:
        with STATE["lock"]:
            now = STATE["clock"]
            st = STATE["store"]
            cache_info = {"hits": st.hits, "misses": st.misses, "hit_rate": st.hit_rate} if st else {"hits": 0, "misses": 0, "hit_rate": 0.0}

        keys = ("request_id", "requester_id", "blood_group", "city", "units_needed", "units_allocated", "priority", "status")
        rows = db._run("SELECT request_id, requester_id, blood_group, city, units_needed, units_allocated, priority, status "
                       "FROM requests ORDER BY request_id DESC LIMIT 40")

        # Pending requests with Requester Names, ordered by Priority (Emergency 0 > Urgent 1 > Routine 2)
        pend_rows = db._run(
            "SELECT r.request_id, r.blood_group, r.city, r.units_needed, r.priority, r.created_at, p.name, r.requester_id "
            "FROM requests r JOIN persons p ON r.requester_id = p.person_id "
            "WHERE r.status='PENDING' ORDER BY r.priority ASC, r.created_at ASC"
        )
        queue = []
        for r in pend_rows:
            queue.append({
                "request_id": r[0],
                "blood_group": r[1],
                "city": r[2],
                "units_needed": r[3],
                "priority": r[4],
                "created_at": r[5],
                "requester_name": r[6],
                "requester_id": r[7]
            })

        # Donor appeals: If logged in as donor, filter appeals matching donor's blood group
        donor_appeals = []
        curr_u = session.get("user")
        if curr_u and curr_u.get("role") == "DONOR" and curr_u.get("person_id"):
            d_pid = curr_u["person_id"]
            d_row = db._run(f"SELECT blood_group, city FROM persons WHERE person_id={db.ph}", (d_pid,))
            if d_row:
                donor_bg, donor_city = d_row[0]
                for q in queue:
                    if rules.can_donate_to(donor_bg, q["blood_group"]):
                        donor_appeals.append(q)

        return jsonify({
            "clock": now,
            "inventory": db.inventory_summary(TODAY),
            "requests": [dict(zip(keys, r)) for r in rows],
            "pending": len(queue),
            "queue": queue,
            "donor_appeals": donor_appeals,
            "cache": cache_info
        })
    finally:
        db.close()


@app.route("/api/inspect_request")
def api_inspect_request():
    rid = int(request.args.get("request_id", 1))
    db = _db()
    try:
        req = db.get_request(rid)
        if not req:
            return jsonify({"error": f"Request #{rid} not found"}), 404

        # Requester details
        p_row = db._run(f"SELECT name, birth_year, city FROM persons WHERE person_id={db.ph}", (req["requester_id"],))
        p_name = p_row[0][0] if p_row else f"Patient #{req['requester_id']}"
        p_age = TODAY.year - p_row[0][1] if p_row else 30

        # Stock check in blood bank
        compat_groups = rules.compatible_donor_groups(req["blood_group"])
        stock_units = db._run(
            f"SELECT COUNT(*) FROM inventory WHERE status='AVAILABLE' AND expiry_date >= {db.ph} "
            f"AND blood_group IN ({','.join([db.ph] * len(compat_groups))})",
            (TODAY.isoformat(), *compat_groups)
        )[0][0]

        # ML Dynamic Link Prediction: Find eligible donors & explain connection pathway
        cands = db.eligible_donors(req["blood_group"], req["city"], TODAY, exclude_id=req["requester_id"])
        rec = DonorRecommender(STATE["store"], STATE["latest"], lam=0.5, window=6)
        ranked = rec.rank(req["requester_id"], cands, k=5, method="recency")

        # Extract Graph connections (mutual neighbors) from recency graph
        w, strength = rec._recency_graph()
        wu = w.get(req["requester_id"], {})

        donors_data = []
        for d_id, sc in ranked:
            d_row = db._run(f"SELECT name, blood_group, birth_year, last_donation FROM persons WHERE person_id={db.ph}", (d_id,))
            if not d_row:
                continue
            d_name, d_bg, d_by, d_ld = d_row[0]
            d_age = TODAY.year - d_by
            
            # Find mutual friends z in graph
            wv = w.get(d_id, {})
            common_z = list(set(wu.keys()) & set(wv.keys()))[:2]
            if common_z:
                z_names = [db._run(f"SELECT name FROM persons WHERE person_id={db.ph}", (z,))[0][0] for z in common_z]
                conn_path = f"Connected via mutual contact: {', '.join(z_names)}"
            else:
                conn_path = f"Direct City Social Circle ({req['city']})"

            donors_data.append({
                "donor_id": d_id,
                "name": d_name,
                "blood_group": d_bg,
                "age": d_age,
                "score": round(sc, 4),
                "connection_path": conn_path,
                "last_seen_months": 1 if sc > 0.4 else 3
            })

        return jsonify({
            "request": {
                **req,
                "requester_name": p_name,
                "age": p_age
            },
            "stock_available": stock_units,
            "donors": donors_data
        })
    finally:
        db.close()


@app.route("/api/graph_network")
def api_graph_network():
    """Returns nodes (Patients: Blue Dots 🔵, Donors: Red Dots 🔴) and connectivity edges."""
    db = _db()
    try:
        # 1. Fetch active patients with requests
        p_rows = db._run(
            "SELECT DISTINCT r.request_id, r.requester_id, p.name, r.blood_group, r.city, r.priority, r.status, r.units_needed "
            "FROM requests r JOIN persons p ON r.requester_id = p.person_id "
            "ORDER BY r.priority ASC, r.request_id DESC LIMIT 12"
        )
        
        # 2. Fetch active eligible donors
        d_rows = db._run(
            "SELECT person_id, name, blood_group, city, birth_year "
            "FROM persons WHERE available=1 AND (last_donation IS NULL OR last_donation <= '2026-07-16') "
            "ORDER BY person_id ASC LIMIT 22"
        )

        patient_map = {}
        for r in p_rows:
            rid, pid, name, bg, city, prio, status, units = r
            if pid not in patient_map:
                patient_map[pid] = {
                    "id": f"p_{pid}",
                    "person_id": pid,
                    "request_id": rid,
                    "name": name,
                    "type": "patient",
                    "blood_group": bg,
                    "city": city,
                    "priority": prio,
                    "status": status,
                    "units": units,
                    "label": f"{name} ({bg})"
                }

        donor_map = {}
        for d in d_rows:
            d_pid, d_name, d_bg, d_city, d_by = d
            if d_pid in patient_map:
                continue
            donor_map[d_pid] = {
                "id": f"d_{d_pid}",
                "person_id": d_pid,
                "name": d_name,
                "type": "donor",
                "blood_group": d_bg,
                "city": d_city,
                "age": TODAY.year - d_by,
                "label": f"{d_name} ({d_bg})"
            }

        # 3. Compute Edges (Social Connections & Link Prediction)
        edges = []
        rec = DonorRecommender(STATE["store"], STATE["latest"], lam=0.5, window=6)
        w, _ = rec._recency_graph()

        for pid, p in patient_map.items():
            compat = rules.compatible_donor_groups(p["blood_group"])
            wu = w.get(pid, {})
            scored_donors = []
            for d_pid, d in donor_map.items():
                if d["blood_group"] in compat:
                    wv = w.get(d_pid, {})
                    common_z = list(set(wu.keys()) & set(wv.keys()))
                    score = 0.35 if d["city"] == p["city"] else 0.15
                    if common_z:
                        score += min(0.6, len(common_z) * 0.2)
                        path = f"Connected via mutual contacts: {len(common_z)} common friend(s)"
                    else:
                        path = f"Community circle in {p['city']}"
                    scored_donors.append((d_pid, score, path))
            
            scored_donors.sort(key=lambda x: x[1], reverse=True)
            for d_pid, score, path in scored_donors[:4]:
                edges.append({
                    "source": f"p_{pid}",
                    "target": f"d_{d_pid}",
                    "score": round(score, 3),
                    "path": path,
                    "patient_name": p["name"],
                    "donor_name": donor_map[d_pid]["name"],
                    "blood_group": p["blood_group"]
                })

        return jsonify({
            "nodes": list(patient_map.values()) + list(donor_map.values()),
            "edges": edges,
            "legend": {
                "patient": {"color": "#3b82f6", "label": "Patient (Blue Dot)"},
                "donor": {"color": "#ef4444", "label": "Voluntary Donor (Red Dot)"}
            }
        })
    finally:
        db.close()


@app.route("/api/request", methods=["POST"])
def api_create_request():
    body = request.get_json() or {}
    bg = body.get("blood_group")
    city = body.get("city")
    units = int(body.get("units", 1))
    prio = int(body.get("priority", 2))
    req_person_id = int(body.get("requester_id", 10))

    if bg not in rules.GROUPS or city not in CITIES:
        return jsonify({"error": "Invalid blood group or city"}), 400
    if prio not in (0, 1, 2):
        return jsonify({"error": "Priority must be 0 (Emergency), 1 (Urgent), or 2 (Routine)"}), 400

    db = _db()
    try:
        with STATE["lock"]:
            STATE["clock"] += 1
            now = STATE["clock"]

        hospital_id = CITIES.index(city) + 1
        rid = db.add_request(req_person_id, hospital_id, bg, city, units, prio, now)

        actor = session.get("user", {}).get("username", f"user_{req_person_id}")
        role = session.get("user", {}).get("role", "USER")
        db.log_audit(actor, role, "SUBMIT_REQUEST", f"Request #{rid} created for {units} units of {bg} in {city} (Prio {prio})", now)

        return jsonify({"request_id": rid, "status": "QUEUED", "clock": now})
    finally:
        db.close()


@app.route("/api/process", methods=["POST"])
@role_required("ADMIN", "STAFF")
def api_process_next():
    data = request.get_json() or {}
    specific_rid = data.get("request_id")

    db = _db()
    try:
        with STATE["lock"]:
            now = STATE["clock"]
            pend = db.pending_requests()
            if not pend:
                return jsonify({"error": "No pending requests in queue"}), 400
            
            if specific_rid:
                rid = int(specific_rid)
            else:
                # OS Priority Scheduling: Pick highest priority (Emergency 0 > Urgent 1 > Routine 2)
                rid, pr, _ = min(pend, key=lambda r: (r[1], r[2], r[0]))

        # DBMS ATOMIC ALLOCATION TRANSACTION
        out = db.allocate_units(rid, TODAY)
        donors = []

        # If shortfall occurs -> ML Dynamic Link Prediction Recommender
        if out["shortfall"] > 0:
            req = db.get_request(rid)
            cands = db.eligible_donors(req["blood_group"], req["city"], TODAY, exclude_id=req["requester_id"])
            rec = DonorRecommender(STATE["store"], STATE["latest"], lam=0.5, window=6)
            ranked = rec.rank(req["requester_id"], cands, k=5, method="recency")
            db.save_notifications(rid, ranked, "recency")
            for i, (d, sc) in enumerate(ranked):
                p = db._run(f"SELECT name, blood_group FROM persons WHERE person_id={db.ph}", (d,))[0]
                donors.append({"rank": i + 1, "donor_id": d, "name": p[0], "blood_group": p[1], "score": round(sc, 4)})

        actor = session.get("user", {}).get("username", "hospital_staff")
        role = session.get("user", {}).get("role", "STAFF")
        db.log_audit(actor, role, "PROCESS_REQUEST",
                     f"Request #{rid} processed -> {out['status']} (Allocated: {out['allocated_now']}, Shortfall: {out['shortfall']})",
                     now)

        return jsonify({**out, "donors": donors})
    finally:
        db.close()


@app.route("/api/inventory/add", methods=["POST"])
@role_required("ADMIN", "STAFF")
def api_add_inventory():
    data = request.get_json() or {}
    hid = int(data.get("hospital_id", 1))
    bg = data.get("blood_group")
    exp = data.get("expiry_date")
    bags = int(data.get("bags", 1))
    donor_name = data.get("donor_name", "Voluntary Donor")

    db = _db()
    try:
        last_uid = None
        for _ in range(max(1, bags)):
            last_uid = db.add_inventory_unit(hid, bg, exp)
        actor = session.get("user", {}).get("username", "staff")
        role = session.get("user", {}).get("role", "STAFF")
        db.log_audit(actor, role, "ADD_INVENTORY", f"Added {bags} bag(s) of {bg} from donor {donor_name} (Exp: {exp})", STATE["clock"])
        return jsonify({"message": f"{bags} unit(s) added", "unit_id": last_uid})
    finally:
        db.close()


@app.route("/api/donor/pledge", methods=["POST"])
@role_required("DONOR")
def api_donor_pledge():
    data = request.get_json() or {}
    rid = int(data.get("request_id", 0))
    user = session["user"]
    db = _db()
    try:
        req = db.get_request(rid)
        if not req:
            return jsonify({"error": "Request not found"}), 404
        db.log_audit(user["username"], "DONOR", "PLEDGE_DONATION",
                     f"Donor {user['username']} pledged blood for Request #{rid} ({req['blood_group']} in {req['city']})",
                     STATE["clock"])
        return jsonify({"message": f"Thank you {user['username']}! Your donation pledge for Request #{rid} has been recorded.", "request_id": rid})
    finally:
        db.close()


@app.route("/api/donor/walkin_donate", methods=["POST"])
@role_required("DONOR")
def api_donor_walkin_donate():
    user = session["user"]
    pid = user.get("person_id")
    if not pid:
        return jsonify({"error": "No person profile linked to this donor"}), 400
    data = request.get_json() or {}
    hid = int(data.get("hospital_id", 1))
    db = _db()
    try:
        p_row = db._run(f"SELECT blood_group, name FROM persons WHERE person_id={db.ph}", (pid,))
        if not p_row:
            return jsonify({"error": "Donor profile not found"}), 404
        bg, name = p_row[0]
        exp = (TODAY + timedelta(days=35)).isoformat()
        uid = db.add_inventory_unit(hid, bg, exp)
        db._run(f"UPDATE persons SET last_donation={db.ph} WHERE person_id={db.ph}", (TODAY.isoformat(), pid))
        db.log_audit(user["username"], "DONOR", "WALKIN_DONATION",
                     f"Donor {name} donated 1 unit of {bg} at Hospital #{hid} (Unit #{uid}, Exp: {exp})",
                     STATE["clock"])
        return jsonify({"message": f"1 unit of {bg} successfully donated and stored in blood bank!", "unit_id": uid})
    finally:
        db.close()


@app.route("/api/clock/advance", methods=["POST"])
def api_advance_clock():
    data = request.get_json() or {}
    minutes = int(data.get("minutes", 15))
    with STATE["lock"]:
        STATE["clock"] += minutes
        now = STATE["clock"]
    return jsonify({"message": f"Clock advanced by {minutes} mins", "clock": now})


@app.route("/api/invariants")
@role_required("ADMIN")
def api_invariants():
    db = _db()
    try:
        res = db.check_invariants()
        return jsonify({"invariants": res})
    finally:
        db.close()


@app.route("/api/audit_logs")
@role_required("ADMIN")
def api_audit_logs():
    db = _db()
    try:
        logs = db.get_audit_logs(limit=50)
        return jsonify({"logs": logs})
    finally:
        db.close()


# ==============================================================================
# SERVER ENTRY POINT
# ==============================================================================
def serve(port=8000, db_path="results/blood/blood_web.db"):
    import blood_app
    blood_app.make_db(build_world(), db_path, with_future_requests=True)
    STATE["path"] = db_path
    db = _db()
    db.seed_default_users()
    STATE["latest"] = db._run("SELECT MAX(snapshot_id) FROM snapshots")[0][0]
    STATE["clock"] = db._run("SELECT COALESCE(MAX(created_at),0) FROM requests")[0][0]
    db.close()
    STATE["store"] = SharedSnapshotStore(lambda: _db(), capacity=9, policy="LRU")

    print("\n" + "=" * 65)
    print("   SonetQ BloodConnect Server Running with Connectivity Graph!")
    print(f"   URL: http://127.0.0.1:{port}")
    print("=" * 65)
    print("Demo Accounts:")
    print("   Hospital Staff:     username='staff'     password='staff123'")
    print("   Patient (Rahul):    username='rahul'     password='user123'")
    print("   Patient (Priya):    username='priya'     password='user123'")
    print("   Donor (Vikram):     username='vikram'    password='donor123'")
    print("   Donor (Sneha):      username='sneha'     password='donor123'")
    print("   Administrator:      username='admin'     password='admin123'")
    print("=" * 65 + "\n")

    app.run(host="0.0.0.0", port=port, debug=False)
