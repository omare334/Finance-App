# finance_app.py
import sys
import os
import sqlite3
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, QDateEdit,
    QLabel, QGroupBox, QTabWidget, QComboBox, QLineEdit, QDoubleSpinBox,
    QHeaderView, QDialog, QDialogButtonBox, QFormLayout, QCheckBox, QSpinBox,
    QCalendarWidget, QTextEdit
)
from PyQt6.QtCore import Qt, QDate
from PyQt6.QtGui import QFont, QColor, QTextCharFormat

DB_FILE = "finance.db"

class Database:
    def __init__(self, db_file=DB_FILE):
        self.db_file = db_file
        self.init_database()
    
    def get_connection(self):
        # Use WAL mode for better concurrency and set timeout
        conn = sqlite3.connect(self.db_file, timeout=20.0)
        # Enable WAL mode for better concurrent access
        conn.execute("PRAGMA journal_mode=WAL")
        return conn
    
    def init_database(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Recurring payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recurring_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_day INTEGER NOT NULL,
                payment_type TEXT DEFAULT 'debit',
                last_paid_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add payment_type column if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE recurring_payments ADD COLUMN payment_type TEXT DEFAULT 'debit'")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
        
        # Add delete_next_month column if it doesn't exist (migration)
        try:
            cursor.execute("ALTER TABLE recurring_payments ADD COLUMN delete_next_month INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
        
        # Add pay_period_months column if it doesn't exist (migration)
        # NULL or -1 means infinite, otherwise number of months
        try:
            cursor.execute("ALTER TABLE recurring_payments ADD COLUMN pay_period_months INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
        
        # Add period_start_date column to track when the pay period started
        try:
            cursor.execute("ALTER TABLE recurring_payments ADD COLUMN period_start_date DATE")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
        
        # Add is_active column to track if payment is still active
        try:
            cursor.execute("ALTER TABLE recurring_payments ADD COLUMN is_active INTEGER DEFAULT 1")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
        
        # Recurring income table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recurring_income (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                income_day INTEGER NOT NULL,
                last_received_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # One-time payments table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS one_time_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_date DATE NOT NULL,
                paid BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Payment history table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payment_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payment_id INTEGER,
                payment_type TEXT NOT NULL,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_date DATE NOT NULL,
                month INTEGER NOT NULL,
                year INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Recent transactions for undo (stores last 10 transactions)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS recent_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                payment_id INTEGER,
                payment_type TEXT NOT NULL,
                name TEXT NOT NULL,
                amount REAL NOT NULL,
                payment_date DATE NOT NULL,
                month INTEGER NOT NULL,
                year INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                old_last_paid_date DATE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Monthly summary table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monthly_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                month INTEGER NOT NULL,
                year INTEGER NOT NULL,
                total_payments REAL DEFAULT 0,
                total_income REAL DEFAULT 0,
                savings_amount REAL DEFAULT 0,
                net_savings REAL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(month, year)
            )
        ''')
        
        # App settings table to track last deletion check
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Add old_last_paid_date column to recent_transactions if it doesn't exist
        try:
            cursor.execute("ALTER TABLE recent_transactions ADD COLUMN old_last_paid_date DATE")
        except sqlite3.OperationalError:
            # Column already exists, ignore
            pass
        
        conn.commit()
        conn.close()

class PaymentDialog(QDialog):
    def __init__(self, parent=None, payment_data=None):
        super().__init__(parent)
        self.payment_data = payment_data
        self.setWindowTitle("Add Recurring Payment" if not payment_data else "Edit Recurring Payment")
        self.setModal(True)
        self.resize(400, 300)
        
        # Apply modern styling
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e);
            }
            QLabel {
                color: #ffffff;
                font-weight: bold;
            }
        """)
        
        layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Payment name")
        layout.addRow("Name:", self.name_edit)
        
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setMaximum(999999.99)
        self.amount_spin.setPrefix("£")
        self.amount_spin.setDecimals(2)
        layout.addRow("Amount:", self.amount_spin)
        
        self.day_spin = QDoubleSpinBox()
        self.day_spin.setMaximum(31)
        self.day_spin.setMinimum(1)
        self.day_spin.setDecimals(0)
        self.day_spin.setSuffix(" of month")
        layout.addRow("Payment Day:", self.day_spin)
        
        self.type_combo = QComboBox()
        self.type_combo.addItems(["Debit", "Credit"])
        layout.addRow("Payment Type:", self.type_combo)
        
        # Pay Period (Infinite or number of months)
        period_layout = QHBoxLayout()
        self.infinite_period_checkbox = QCheckBox("Infinite (recur forever)")
        self.infinite_period_checkbox.setChecked(True)  # Default to infinite
        self.infinite_period_checkbox.stateChanged.connect(self.toggle_period_input)
        period_layout.addWidget(self.infinite_period_checkbox)
        
        period_input_layout = QHBoxLayout()
        period_input_layout.addWidget(QLabel("Or for:"))
        self.period_spin = QSpinBox()
        self.period_spin.setMinimum(1)
        self.period_spin.setMaximum(999)
        self.period_spin.setValue(5)
        self.period_spin.setSuffix(" months")
        self.period_spin.setEnabled(False)  # Disabled when infinite is checked
        period_input_layout.addWidget(self.period_spin)
        period_layout.addLayout(period_input_layout)
        period_layout.addStretch()
        
        period_widget = QWidget()
        period_widget.setLayout(period_layout)
        layout.addRow("Pay Period:", period_widget)
        
        if payment_data:
            self.name_edit.setText(payment_data[1])
            self.amount_spin.setValue(payment_data[2])
            self.day_spin.setValue(payment_data[3])
            # Handle payment_type (may not exist in old data)
            if len(payment_data) > 5:
                payment_type = payment_data[5] if payment_data[5] else 'debit'
            else:
                payment_type = 'debit'
            if payment_type.lower() == 'credit':
                self.type_combo.setCurrentIndex(1)
            else:
                self.type_combo.setCurrentIndex(0)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
        self.setLayout(layout)
    
    def toggle_period_input(self, state):
        """Enable/disable period spinbox based on infinite checkbox"""
        self.period_spin.setEnabled(not self.infinite_period_checkbox.isChecked())
    
    def get_data(self):
        # If infinite is checked, return None for pay_period_months
        # Otherwise return the number of months
        pay_period_months = None if self.infinite_period_checkbox.isChecked() else self.period_spin.value()
        
        return {
            'name': self.name_edit.text().strip(),
            'amount': self.amount_spin.value(),
            'payment_day': int(self.day_spin.value()),
            'payment_type': self.type_combo.currentText().lower(),
            'pay_period_months': pay_period_months
        }

class IncomeDialog(QDialog):
    def __init__(self, parent=None, income_data=None):
        super().__init__(parent)
        self.income_data = income_data
        self.setWindowTitle("Add Recurring Income" if not income_data else "Edit Recurring Income")
        self.setModal(True)
        self.resize(400, 250)
        
        # Apply modern styling
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e);
            }
            QLabel {
                color: #ffffff;
                font-weight: bold;
            }
        """)
        
        layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Income source name")
        layout.addRow("Name:", self.name_edit)
        
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setMaximum(999999.99)
        self.amount_spin.setPrefix("£")
        self.amount_spin.setDecimals(2)
        layout.addRow("Amount:", self.amount_spin)
        
        self.day_spin = QDoubleSpinBox()
        self.day_spin.setMaximum(31)
        self.day_spin.setMinimum(1)
        self.day_spin.setDecimals(0)
        self.day_spin.setSuffix(" of month")
        layout.addRow("Income Day:", self.day_spin)
        
        if income_data:
            self.name_edit.setText(income_data[1])
            self.amount_spin.setValue(income_data[2])
            self.day_spin.setValue(income_data[3])
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
        self.setLayout(layout)
    
    def get_data(self):
        return {
            'name': self.name_edit.text().strip(),
            'amount': self.amount_spin.value(),
            'income_day': int(self.day_spin.value())
        }

class OneTimePaymentDialog(QDialog):
    def __init__(self, parent=None, payment_data=None):
        super().__init__(parent)
        self.payment_data = payment_data
        self.setWindowTitle("Add One-Time Payment" if not payment_data else "Edit One-Time Payment")
        self.setModal(True)
        self.resize(400, 250)
        
        # Apply modern styling
        self.setStyleSheet("""
            QDialog {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e);
            }
            QLabel {
                color: #ffffff;
                font-weight: bold;
            }
        """)
        
        layout = QFormLayout()
        
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("Payment name")
        layout.addRow("Name:", self.name_edit)
        
        self.amount_spin = QDoubleSpinBox()
        self.amount_spin.setMaximum(999999.99)
        self.amount_spin.setPrefix("£")
        self.amount_spin.setDecimals(2)
        layout.addRow("Amount:", self.amount_spin)
        
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate())
        layout.addRow("Payment Date:", self.date_edit)
        
        if payment_data:
            self.name_edit.setText(payment_data[1])
            self.amount_spin.setValue(payment_data[2])
            date = datetime.strptime(payment_data[3], "%Y-%m-%d").date()
            self.date_edit.setDate(QDate(date.year, date.month, date.day))
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)
        
        self.setLayout(layout)
    
    def get_data(self):
        return {
            'name': self.name_edit.text().strip(),
            'amount': self.amount_spin.value(),
            'payment_date': self.date_edit.date().toString("yyyy-MM-dd")
        }

class FinanceApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = Database()
        self.setWindowTitle("Finance Tracker")
        self.resize(1400, 900)
        
        # Set modern dark theme with enhanced styling
        self.setStyleSheet("""
            QMainWindow {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e);
                color: #ffffff;
            }
            QWidget {
                background: transparent;
                color: #ffffff;
            }
            QGroupBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2d3748, stop:1 #1a202c);
                border: 2px solid #4a5568;
                border-radius: 10px;
                margin-top: 15px;
                padding-top: 15px;
                color: #ffffff;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 5px 10px;
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                border-radius: 5px;
                color: #ffffff;
                font-weight: bold;
            }
            QTableWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2d3748, stop:1 #1a202c);
                color: #ffffff;
                gridline-color: #4a5568;
                border: 2px solid #4a5568;
                border-radius: 8px;
                selection-background-color: #667eea;
                selection-color: #ffffff;
            }
            QTableWidget::item {
                background-color: transparent;
                color: #ffffff;
                padding: 5px;
            }
            QTableWidget::item:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                color: #ffffff;
            }
            QTableWidget::item:hover {
                background-color: #4a5568;
            }
            QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                color: #ffffff;
                padding: 8px;
                border: none;
                font-weight: bold;
            }
            QTabWidget::pane {
                border: 2px solid #4a5568;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e);
                border-radius: 8px;
            }
            QTabBar::tab {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2d3748, stop:1 #1a202c);
                color: #a0aec0;
                padding: 10px 20px;
                margin-right: 3px;
                border-top-left-radius: 8px;
                border-top-right-radius: 8px;
                border: 1px solid #4a5568;
                font-weight: bold;
            }
            QTabBar::tab:selected {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                color: #ffffff;
                border-bottom: 2px solid #667eea;
            }
            QTabBar::tab:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #3d4758, stop:1 #2a3448);
                color: #ffffff;
            }
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 11pt;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #7c8bf0, stop:1 #8a5fb8);
                transform: scale(1.05);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #5568d9, stop:1 #6a3a92);
            }
            QLineEdit, QDoubleSpinBox, QDateEdit {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2d3748, stop:1 #1a202c);
                color: #ffffff;
                border: 2px solid #4a5568;
                border-radius: 6px;
                padding: 6px;
                selection-background-color: #667eea;
            }
            QLineEdit:focus, QDoubleSpinBox:focus, QDateEdit:focus {
                border: 2px solid #667eea;
            }
            QComboBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2d3748, stop:1 #1a202c);
                color: #ffffff;
                border: 2px solid #4a5568;
                border-radius: 6px;
                padding: 5px;
            }
            QComboBox:hover {
                border: 2px solid #667eea;
            }
            QComboBox::drop-down {
                border: none;
                background: transparent;
            }
            QComboBox::down-arrow {
                image: none;
                border-left: 5px solid transparent;
                border-right: 5px solid transparent;
                border-top: 5px solid #ffffff;
                margin-right: 5px;
            }
            QComboBox QAbstractItemView {
                background: #2d3748;
                border: 2px solid #667eea;
                border-radius: 6px;
                selection-background-color: #667eea;
                selection-color: #ffffff;
            }
            QLabel {
                color: #ffffff;
            }
            QScrollBar:vertical {
                background: #2d3748;
                width: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                min-height: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:vertical:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #7c8bf0, stop:1 #8a5fb8);
            }
            QScrollBar:horizontal {
                background: #2d3748;
                height: 12px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                min-width: 20px;
                border-radius: 6px;
            }
            QScrollBar::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #7c8bf0, stop:1 #8a5fb8);
            }
            QMessageBox {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #1a1a2e, stop:1 #16213e);
            }
            QMessageBox QLabel {
                color: #ffffff;
            }
            QMessageBox QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                color: #ffffff;
                border: none;
                padding: 8px 16px;
                border-radius: 6px;
                font-weight: bold;
                min-width: 80px;
            }
            QMessageBox QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #7c8bf0, stop:1 #8a5fb8);
            }
        """)
        
        # Create tabs
        self.tabs = QTabWidget()
        
        # Summary Tab (first tab)
        self.summary_tab = self.create_summary_tab()
        self.tabs.addTab(self.summary_tab, "📊 Summary")
        
        # Recurring Payments Tab
        self.recurring_payments_tab = self.create_recurring_payments_tab()
        self.tabs.addTab(self.recurring_payments_tab, "Recurring Payments")
        
        # Recurring Income Tab
        self.recurring_income_tab = self.create_recurring_income_tab()
        self.tabs.addTab(self.recurring_income_tab, "Recurring Income")
        
        # One-Time Payments Tab
        self.one_time_payments_tab = self.create_one_time_payments_tab()
        self.tabs.addTab(self.one_time_payments_tab, "One-Time Payments")
        
        # History Tab
        self.history_tab = self.create_history_tab()
        self.tabs.addTab(self.history_tab, "History")
        
        # Calendar Tab
        self.calendar_tab = self.create_calendar_tab()
        self.tabs.addTab(self.calendar_tab, "📅 Calendar")
        
        # Main layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # Auto-update on startup
        self.update_payment_dates()
        
        # Check and disable expired payments
        self.check_and_disable_expired_payments()
        
        # Check and delete payments marked for deletion next month
        self.check_and_delete_pending_deletions()
    
    def create_summary_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Title
        title_label = QLabel(f"<h1 style='color: #ffffff; text-align: center;'>📊 Financial Summary - {datetime.today().strftime('%B %Y')}</h1>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 #667eea, stop:1 #764ba2);
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 10px;
        """)
        layout.addWidget(title_label)
        
        # Refresh and Test Notification buttons
        button_layout = QHBoxLayout()
        refresh_btn = QPushButton("🔄 Refresh Summary")
        refresh_btn.clicked.connect(self.load_summary)
        test_notification_btn = QPushButton("🔔 Test Notification")
        test_notification_btn.clicked.connect(self.test_notification)
        button_layout.addStretch()
        button_layout.addWidget(refresh_btn)
        button_layout.addWidget(test_notification_btn)
        button_layout.addStretch()
        layout.addLayout(button_layout)
        
        # Summary boxes
        summary_layout = QHBoxLayout()
        
        # Income box
        income_box = QGroupBox("💰 Income This Month")
        income_layout = QVBoxLayout()
        self.income_label = QLabel()
        self.income_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.income_label.setStyleSheet("""
            color: #48bb78;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(72, 187, 120, 0.2), stop:1 transparent);
            border-radius: 8px;
            padding: 10px;
        """)
        self.income_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        income_layout.addWidget(self.income_label)
        income_box.setLayout(income_layout)
        
        # Money Out box
        money_out_box = QGroupBox("💸 Total Payments Scheduled")
        money_out_layout = QVBoxLayout()
        self.money_out_label = QLabel()
        self.money_out_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.money_out_label.setStyleSheet("""
            color: #f56565;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(245, 101, 101, 0.2), stop:1 transparent);
            border-radius: 8px;
            padding: 10px;
        """)
        self.money_out_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        money_out_layout.addWidget(self.money_out_label)
        money_out_box.setLayout(money_out_layout)
        
        # Already Paid box
        paid_box = QGroupBox("✅ Already Paid This Month")
        paid_layout = QVBoxLayout()
        self.paid_label = QLabel()
        self.paid_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.paid_label.setStyleSheet("""
            color: #48bb78;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(72, 187, 120, 0.2), stop:1 transparent);
            border-radius: 8px;
            padding: 10px;
        """)
        self.paid_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        paid_layout.addWidget(self.paid_label)
        paid_box.setLayout(paid_layout)
        
        # To Be Paid box
        to_pay_box = QGroupBox("⏳ To Be Paid This Month")
        to_pay_layout = QVBoxLayout()
        self.to_pay_label = QLabel()
        self.to_pay_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.to_pay_label.setStyleSheet("""
            color: #ed8936;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(237, 137, 54, 0.2), stop:1 transparent);
            border-radius: 8px;
            padding: 10px;
        """)
        self.to_pay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        to_pay_layout.addWidget(self.to_pay_label)
        to_pay_box.setLayout(to_pay_layout)
        
        summary_layout.addWidget(income_box)
        summary_layout.addWidget(money_out_box)
        summary_layout.addWidget(paid_box)
        summary_layout.addWidget(to_pay_box)
        
        layout.addLayout(summary_layout)
        
        # Credit and Debit breakdown
        credit_debit_layout = QHBoxLayout()
        
        # Remaining Credit box
        remaining_credit_box = QGroupBox("💳 Remaining Credit This Month")
        remaining_credit_layout = QVBoxLayout()
        self.remaining_credit_label = QLabel()
        self.remaining_credit_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.remaining_credit_label.setStyleSheet("""
            color: #38b2ac;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(56, 178, 172, 0.2), stop:1 transparent);
            border-radius: 8px;
            padding: 10px;
        """)
        self.remaining_credit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        remaining_credit_layout.addWidget(self.remaining_credit_label)
        remaining_credit_box.setLayout(remaining_credit_layout)
        
        # Remaining Debit box
        remaining_debit_box = QGroupBox("💸 Remaining Debit This Month")
        remaining_debit_layout = QVBoxLayout()
        self.remaining_debit_label = QLabel()
        self.remaining_debit_label.setFont(QFont("Arial", 16, QFont.Weight.Bold))
        self.remaining_debit_label.setStyleSheet("""
            color: #f56565;
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 rgba(245, 101, 101, 0.2), stop:1 transparent);
            border-radius: 8px;
            padding: 10px;
        """)
        self.remaining_debit_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        remaining_debit_layout.addWidget(self.remaining_debit_label)
        remaining_debit_box.setLayout(remaining_debit_layout)
        
        credit_debit_layout.addWidget(remaining_credit_box)
        credit_debit_layout.addWidget(remaining_debit_box)
        
        layout.addLayout(credit_debit_layout)
        
        # Net Savings box (separate row for emphasis)
        net_savings_layout = QHBoxLayout()
        net_savings_layout.addStretch()
        
        net_savings_box = QGroupBox("💵 Net Savings This Month")
        net_savings_box_layout = QVBoxLayout()
        self.net_savings_label = QLabel()
        self.net_savings_label.setFont(QFont("Arial", 20, QFont.Weight.Bold))
        self.net_savings_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.net_savings_label.setStyleSheet("""
            padding: 15px;
            border-radius: 10px;
        """)
        net_savings_box_layout.addWidget(self.net_savings_label)
        net_savings_box.setLayout(net_savings_box_layout)
        net_savings_box.setMinimumWidth(350)
        
        net_savings_layout.addWidget(net_savings_box)
        net_savings_layout.addStretch()
        
        layout.addLayout(net_savings_layout)
        
        # Next 5 Scheduled Payments
        next_payments_box = QGroupBox("📅 Next 5 Scheduled Payments")
        next_payments_layout = QVBoxLayout()
        
        self.next_payments_table = QTableWidget()
        self.next_payments_table.setColumnCount(4)
        self.next_payments_table.setHorizontalHeaderLabels([
            "Date", "Name", "Amount", "Type"
        ])
        self.next_payments_table.horizontalHeader().setStretchLastSection(True)
        self.next_payments_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.next_payments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.next_payments_table.setMaximumHeight(200)
        
        next_payments_layout.addWidget(self.next_payments_table)
        next_payments_box.setLayout(next_payments_layout)
        
        layout.addWidget(next_payments_box)
        layout.addStretch()
        
        widget.setLayout(layout)
        self.load_summary()
        return widget
    
    def load_summary(self):
        """Load and display summary information"""
        today = datetime.today().date()
        current_month = today.month
        current_year = today.year
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # 1. Income coming in for this month (from recurring income)
            cursor.execute("SELECT amount FROM recurring_income")
            recurring_income_list = cursor.fetchall()
            total_income = sum(income[0] for income in recurring_income_list) if recurring_income_list else 0
            
            # Also check if income was already received this month
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM payment_history
                WHERE payment_type = 'income' AND month = ? AND year = ?
            """, (current_month, current_year))
            received_income = cursor.fetchone()[0] or 0
            
            # 2. Money coming out (total scheduled payments - recurring + one-time for this month)
            # Separate credit and debit (only active payments)
            cursor.execute("SELECT amount, payment_type FROM recurring_payments WHERE COALESCE(is_active, 1) = 1")
            recurring_payments_list = cursor.fetchall()
            total_recurring = 0
            total_credit = 0
            total_debit = 0
            
            for payment in recurring_payments_list:
                amount = payment[0]
                payment_type = payment[1] if len(payment) > 1 and payment[1] else 'debit'
                total_recurring += amount
                if payment_type and payment_type.lower() == 'credit':
                    total_credit += amount
                else:
                    total_debit += amount
            
            # One-time payments for this month (count as debit)
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM one_time_payments
                WHERE strftime('%m', payment_date) = ? AND strftime('%Y', payment_date) = ?
            """, (f"{current_month:02d}", str(current_year)))
            one_time_total = cursor.fetchone()[0] or 0
            total_debit += one_time_total  # One-time payments are debit
            
            total_money_out = total_recurring + one_time_total
            
            # 3. Money already paid from scheduled payments this month
            # Separate by credit/debit
            cursor.execute("""
                SELECT ph.amount, ph.payment_id, ph.payment_type as hist_type, rp.payment_type
                FROM payment_history ph
                LEFT JOIN recurring_payments rp ON ph.payment_id = rp.id AND ph.payment_type = 'recurring'
                WHERE ph.payment_type IN ('recurring', 'one_time') AND ph.month = ? AND ph.year = ?
            """, (current_month, current_year))
            paid_payments = cursor.fetchall()
            
            already_paid = 0
            credit_paid = 0
            debit_paid = 0
            
            for paid in paid_payments:
                amount = paid[0]
                hist_type = paid[2]  # payment_type from payment_history
                payment_type = paid[3] if len(paid) > 3 and paid[3] else 'debit'
                
                # If it's a one_time payment, it's always debit
                if hist_type == 'one_time':
                    payment_type = 'debit'
                
                already_paid += amount
                if payment_type and payment_type.lower() == 'credit':
                    credit_paid += amount
                else:
                    debit_paid += amount
            
            # 4. Money to be paid (total scheduled - already paid)
            to_be_paid = total_money_out - already_paid
            remaining_credit = total_credit - credit_paid
            remaining_debit = total_debit - debit_paid
            
            # 5. Next 5 scheduled payments
            all_upcoming_payments = []
            
            # Get recurring payments with their next payment dates (only active)
            cursor.execute("""
                SELECT id, name, amount, payment_day, 
                       COALESCE(payment_type, 'debit') as payment_type,
                       last_paid_date 
                FROM recurring_payments
                WHERE COALESCE(is_active, 1) = 1
            """)
            recurring_payments = cursor.fetchall()
            
            for payment in recurring_payments:
                payment_id, name, amount, payment_day, payment_type, last_paid_date = payment
                # Calculate next payment date
                last_month_date, this_month_date, next_month_date = self.calculate_payment_dates(
                    payment_day, last_paid_date, current_month, current_year
                )
                
                # Check if already paid this month
                cursor.execute("""
                    SELECT COUNT(*) FROM payment_history
                    WHERE payment_id = ? AND payment_type = 'recurring'
                    AND month = ? AND year = ?
                """, (payment_id, current_month, current_year))
                
                if cursor.fetchone()[0] == 0:
                    # Not paid this month, use this month's date
                    if this_month_date >= today:
                        all_upcoming_payments.append((this_month_date, name, amount, "Recurring"))
                else:
                    # Already paid, use next month's date
                    all_upcoming_payments.append((next_month_date, name, amount, "Recurring"))
            
            # Get one-time payments that are unpaid and upcoming
            cursor.execute("""
                SELECT id, name, amount, payment_date FROM one_time_payments
                WHERE paid = 0 AND payment_date >= date('now')
                ORDER BY payment_date
            """)
            one_time_payments = cursor.fetchall()
            
            for payment_id, name, amount, payment_date_str in one_time_payments:
                payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
                all_upcoming_payments.append((payment_date, name, amount, "One-Time"))
            
            # Sort by date and take next 5
            all_upcoming_payments.sort(key=lambda x: x[0])
            next_5_payments = all_upcoming_payments[:5]
            
            # 6. Get savings amount for this month
            cursor.execute("""
                SELECT savings_amount FROM monthly_summary
                WHERE month = ? AND year = ?
            """, (current_month, current_year))
            savings_result = cursor.fetchone()
            savings_amount = savings_result[0] if savings_result and savings_result[0] else 0
            
            # Calculate net savings: Income - Payments - Savings
            net_savings = total_income - total_money_out - savings_amount
            
            conn.close()
            
            # Update labels
            self.income_label.setText(f"£{total_income:,.2f}\n(Received: £{received_income:,.2f})")
            self.money_out_label.setText(f"£{total_money_out:,.2f}")
            self.paid_label.setText(f"£{already_paid:,.2f}")
            self.to_pay_label.setText(f"£{to_be_paid:,.2f}")
            self.remaining_credit_label.setText(f"£{remaining_credit:,.2f}\n(Scheduled: £{total_credit:,.2f})")
            self.remaining_debit_label.setText(f"£{remaining_debit:,.2f}\n(Scheduled: £{total_debit:,.2f})")
            
            # Update net savings label with color coding and enhanced styling
            if net_savings >= 0:
                self.net_savings_label.setText(f"£{net_savings:,.2f}")
                self.net_savings_label.setStyleSheet("""
                    color: #48bb78;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 rgba(72, 187, 120, 0.3), stop:1 rgba(72, 187, 120, 0.1));
                    border: 2px solid #48bb78;
                    border-radius: 10px;
                    padding: 15px;
                """)
            else:
                self.net_savings_label.setText(f"-£{abs(net_savings):,.2f}")
                self.net_savings_label.setStyleSheet("""
                    color: #f56565;
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                        stop:0 rgba(245, 101, 101, 0.3), stop:1 rgba(245, 101, 101, 0.1));
                    border: 2px solid #f56565;
                    border-radius: 10px;
                    padding: 15px;
                """)
            
            # Update next payments table
            self.next_payments_table.setRowCount(len(next_5_payments))
            for row_idx, (payment_date, name, amount, ptype) in enumerate(next_5_payments):
                self.next_payments_table.setItem(row_idx, 0, QTableWidgetItem(payment_date.strftime("%d/%m/%Y")))
                self.next_payments_table.setItem(row_idx, 1, QTableWidgetItem(name))
                self.next_payments_table.setItem(row_idx, 2, QTableWidgetItem(f"£{amount:,.2f}"))
                self.next_payments_table.setItem(row_idx, 3, QTableWidgetItem(ptype))
                
                # Highlight if due today or overdue
                if payment_date <= today:
                    for col in range(4):
                        item = self.next_payments_table.item(row_idx, col)
                        if item:
                            item.setForeground(Qt.GlobalColor.yellow)
        
        except Exception as e:
            conn.close()
            print(f"Error loading summary: {e}")
            self.income_label.setText("Error loading data")
            self.money_out_label.setText("Error loading data")
            self.paid_label.setText("Error loading data")
            self.to_pay_label.setText("Error loading data")
            self.remaining_credit_label.setText("Error loading data")
            self.remaining_debit_label.setText("Error loading data")
            self.net_savings_label.setText("Error loading data")
            self.net_savings_label.setStyleSheet("color: #FF5722;")
    
    def test_notification(self):
        """Test the notification service"""
        import subprocess
        import os
        
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "notification_service.py")
        
        if not os.path.exists(script_path):
            QMessageBox.warning(
                self, 
                "Notification Service Not Found",
                f"Could not find notification_service.py at:\n{script_path}\n\nPlease make sure the file exists."
            )
            return
        
        try:
            # Run the notification service
            result = subprocess.run(
                ["python3", script_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                QMessageBox.information(
                    self,
                    "Notification Sent",
                    "Test notifications have been sent!\n\nCheck your macOS notifications to see them."
                )
            else:
                QMessageBox.warning(
                    self,
                    "Notification Error",
                    f"Notification service returned an error:\n\n{result.stderr}\n\nCheck the notification_error.log file for details."
                )
        except subprocess.TimeoutExpired:
            QMessageBox.warning(
                self,
                "Timeout",
                "The notification service took too long to run."
            )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Error",
                f"Failed to run notification service:\n\n{str(e)}"
            )
    
    def create_recurring_payments_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Buttons
        button_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Payment")
        add_btn.clicked.connect(self.add_recurring_payment)
        edit_btn = QPushButton("✏️ Edit Payment")
        edit_btn.clicked.connect(self.edit_recurring_payment)
        delete_btn = QPushButton("🗑️ Delete Payment")
        delete_btn.clicked.connect(self.delete_recurring_payment)
        delete_next_month_btn = QPushButton("🗑️ Delete Next Month")
        delete_next_month_btn.clicked.connect(self.mark_delete_next_month)
        mark_paid_btn = QPushButton("✅ Mark as Paid")
        mark_paid_btn.clicked.connect(self.mark_recurring_payment_paid)
        detect_btn = QPushButton("🔍 Detect Payments")
        detect_btn.clicked.connect(self.detect_payments)
        undo_btn = QPushButton("↩️ Undo Last Payment")
        undo_btn.clicked.connect(self.undo_last_payment)
        refresh_btn = QPushButton("🔄 Refresh")
        refresh_btn.clicked.connect(self.update_payment_dates)
        
        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(delete_btn)
        button_layout.addWidget(delete_next_month_btn)
        button_layout.addWidget(mark_paid_btn)
        button_layout.addWidget(detect_btn)
        button_layout.addWidget(undo_btn)
        button_layout.addWidget(refresh_btn)
        button_layout.addStretch()
        
        # Table
        self.recurring_payments_table = QTableWidget()
        self.recurring_payments_table.setColumnCount(9)
        self.recurring_payments_table.setHorizontalHeaderLabels([
            "ID", "Name", "Amount", "Type", "Payment Day", "Last Month", "This Month", "Next Month", "Status"
        ])
        self.recurring_payments_table.horizontalHeader().setStretchLastSection(True)
        self.recurring_payments_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.recurring_payments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        layout.addLayout(button_layout)
        layout.addWidget(self.recurring_payments_table)
        
        widget.setLayout(layout)
        self.load_recurring_payments()
        return widget
    
    def create_recurring_income_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Buttons
        button_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Income")
        add_btn.clicked.connect(self.add_recurring_income)
        edit_btn = QPushButton("✏️ Edit Income")
        edit_btn.clicked.connect(self.edit_recurring_income)
        delete_btn = QPushButton("🗑️ Delete Income")
        delete_btn.clicked.connect(self.delete_recurring_income)
        mark_received_btn = QPushButton("✅ Mark as Received")
        mark_received_btn.clicked.connect(self.mark_recurring_income_received)
        undo_income_btn = QPushButton("↩️ Undo Last Income")
        undo_income_btn.clicked.connect(self.undo_last_payment)
        
        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(delete_btn)
        button_layout.addWidget(mark_received_btn)
        button_layout.addWidget(undo_income_btn)
        button_layout.addStretch()
        
        # Table
        self.recurring_income_table = QTableWidget()
        self.recurring_income_table.setColumnCount(5)
        self.recurring_income_table.setHorizontalHeaderLabels([
            "ID", "Name", "Amount", "Income Day", "Last Received"
        ])
        self.recurring_income_table.horizontalHeader().setStretchLastSection(True)
        self.recurring_income_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.recurring_income_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        layout.addLayout(button_layout)
        layout.addWidget(self.recurring_income_table)
        
        widget.setLayout(layout)
        self.load_recurring_income()
        return widget
    
    def create_one_time_payments_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Buttons
        button_layout = QHBoxLayout()
        add_btn = QPushButton("➕ Add Payment")
        add_btn.clicked.connect(self.add_one_time_payment)
        edit_btn = QPushButton("✏️ Edit Payment")
        edit_btn.clicked.connect(self.edit_one_time_payment)
        delete_btn = QPushButton("🗑️ Delete Payment")
        delete_btn.clicked.connect(self.delete_one_time_payment)
        mark_paid_btn = QPushButton("✅ Mark as Paid")
        mark_paid_btn.clicked.connect(self.mark_one_time_payment_paid)
        undo_one_time_btn = QPushButton("↩️ Undo Last Payment")
        undo_one_time_btn.clicked.connect(self.undo_last_payment)
        
        button_layout.addWidget(add_btn)
        button_layout.addWidget(edit_btn)
        button_layout.addWidget(delete_btn)
        button_layout.addWidget(mark_paid_btn)
        button_layout.addWidget(undo_one_time_btn)
        button_layout.addStretch()
        
        # Table
        self.one_time_payments_table = QTableWidget()
        self.one_time_payments_table.setColumnCount(5)
        self.one_time_payments_table.setHorizontalHeaderLabels([
            "ID", "Name", "Amount", "Payment Date", "Status"
        ])
        self.one_time_payments_table.horizontalHeader().setStretchLastSection(True)
        self.one_time_payments_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.one_time_payments_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        layout.addLayout(button_layout)
        layout.addWidget(self.one_time_payments_table)
        
        widget.setLayout(layout)
        self.load_one_time_payments()
        return widget
    
    def create_history_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Summary section
        summary_group = QGroupBox("Monthly Summary")
        summary_layout = QVBoxLayout()
        
        self.summary_label = QLabel()
        self.summary_label.setFont(QFont("Arial", 12))
        summary_layout.addWidget(self.summary_label)
        
        # Savings input and refresh button
        savings_layout = QHBoxLayout()
        savings_label = QLabel("Savings Amount for Current Month:")
        self.savings_input = QDoubleSpinBox()
        self.savings_input.setMaximum(999999.99)
        self.savings_input.setPrefix("£")
        self.savings_input.setDecimals(2)
        save_savings_btn = QPushButton("💾 Save Savings")
        save_savings_btn.clicked.connect(self.save_current_month_savings)
        refresh_history_btn = QPushButton("🔄 Refresh History")
        refresh_history_btn.clicked.connect(self.refresh_history)
        
        savings_layout.addWidget(savings_label)
        savings_layout.addWidget(self.savings_input)
        savings_layout.addWidget(save_savings_btn)
        savings_layout.addWidget(refresh_history_btn)
        savings_layout.addStretch()
        
        summary_layout.addLayout(savings_layout)
        summary_group.setLayout(summary_layout)
        
        # History table
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "Month/Year", "Total Payments", "Total Income", "Savings", "Net Savings", "Actions", ""
        ])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        
        layout.addWidget(summary_group)
        layout.addWidget(self.history_table)
        
        widget.setLayout(layout)
        self.load_history()
        return widget
    
    # Database operations for recurring payments
    def load_recurring_payments(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        # Use explicit column names to ensure correct order regardless of ALTER TABLE
        cursor.execute("""
            SELECT id, name, amount, payment_day, 
                   COALESCE(payment_type, 'debit') as payment_type,
                   last_paid_date, created_at,
                   COALESCE(delete_next_month, 0) as delete_next_month,
                   pay_period_months, period_start_date,
                   COALESCE(is_active, 1) as is_active
            FROM recurring_payments 
            ORDER BY name
        """)
        payments = cursor.fetchall()
        conn.close()
        
        self.recurring_payments_table.setRowCount(len(payments))
        today = datetime.today().date()
        current_month = today.month
        current_year = today.year
        
        for row_idx, payment in enumerate(payments):
            # Column order: id, name, amount, payment_day, payment_type, last_paid_date, created_at, delete_next_month, pay_period_months, period_start_date, is_active
            payment_id, name, amount, payment_day, payment_type, last_paid_date, created_at, delete_next_month, pay_period_months, period_start_date, is_active = payment
            
            # Calculate dates
            last_month_date, this_month_date, next_month_date = self.calculate_payment_dates(
                payment_day, last_paid_date, current_month, current_year
            )
            
            # ID
            self.recurring_payments_table.setItem(row_idx, 0, QTableWidgetItem(str(payment_id)))
            
            # Name
            self.recurring_payments_table.setItem(row_idx, 1, QTableWidgetItem(name))
            
            # Amount
            self.recurring_payments_table.setItem(row_idx, 2, QTableWidgetItem(f"£{amount:,.2f}"))
            
            # Payment Type
            type_item = QTableWidgetItem(payment_type.capitalize() if payment_type else "Debit")
            if payment_type and payment_type.lower() == 'credit':
                type_item.setForeground(Qt.GlobalColor.cyan)
            else:
                type_item.setForeground(Qt.GlobalColor.red)
            self.recurring_payments_table.setItem(row_idx, 3, type_item)
            
            # Payment Day
            self.recurring_payments_table.setItem(row_idx, 4, QTableWidgetItem(f"Day {int(payment_day)}"))
            
            # Last Month
            self.recurring_payments_table.setItem(row_idx, 5, QTableWidgetItem(last_month_date.strftime("%d/%m/%Y")))
            
            # This Month
            item = QTableWidgetItem(this_month_date.strftime("%d/%m/%Y"))
            if this_month_date <= today:
                item.setForeground(Qt.GlobalColor.yellow)  # Overdue or due today
            self.recurring_payments_table.setItem(row_idx, 6, item)
            
            # Next Month
            self.recurring_payments_table.setItem(row_idx, 7, QTableWidgetItem(next_month_date.strftime("%d/%m/%Y")))
            
            # Status (Delete Next Month indicator + Pay Period info)
            status_parts = []
            
            if not is_active or is_active == 0:
                status_parts.append("❌ Inactive")
            elif delete_next_month and delete_next_month == 1:
                status_parts.append("🗑️ Delete Next Month")
            else:
                status_parts.append("✅ Active")
            
            # Add pay period info
            if pay_period_months is None or pay_period_months == -1:
                status_parts.append("∞ Infinite")
            else:
                # Calculate remaining months
                if period_start_date:
                    try:
                        if isinstance(period_start_date, str):
                            try:
                                start_date = datetime.strptime(period_start_date, "%Y-%m-%d %H:%M:%S").date()
                            except ValueError:
                                start_date = datetime.strptime(period_start_date, "%Y-%m-%d").date()
                        else:
                            start_date = period_start_date
                        
                        # Calculate months elapsed
                        months_elapsed = (today.year - start_date.year) * 12 + (today.month - start_date.month)
                        remaining_months = pay_period_months - months_elapsed
                        
                        if remaining_months <= 0:
                            status_parts.append("⏰ Expired")
                        else:
                            status_parts.append(f"{remaining_months} months left")
                    except:
                        status_parts.append(f"{pay_period_months} months")
                else:
                    status_parts.append(f"{pay_period_months} months")
            
            status_text = " | ".join(status_parts)
            status_item = QTableWidgetItem(status_text)
            
            if not is_active or is_active == 0:
                status_item.setForeground(Qt.GlobalColor.gray)
            elif delete_next_month and delete_next_month == 1:
                status_item.setForeground(Qt.GlobalColor.red)
            elif "Expired" in status_text:
                status_item.setForeground(Qt.GlobalColor.yellow)
            else:
                status_item.setForeground(Qt.GlobalColor.green)
            
            self.recurring_payments_table.setItem(row_idx, 8, status_item)
    
    def calculate_payment_dates(self, payment_day, last_paid_date, current_month, current_year):
        today = datetime.today().date()
        
        # Calculate this month's payment date
        try:
            this_month_date = datetime(current_year, current_month, int(payment_day)).date()
        except ValueError:
            # Handle day 31 in months with fewer days
            last_day = (datetime(current_year, current_month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            this_month_date = last_day
        
        # Calculate last month's payment date
        if last_paid_date:
            # Handle both date-only and datetime strings
            try:
                # Try parsing as datetime first (includes time)
                last_paid = datetime.strptime(str(last_paid_date), "%Y-%m-%d %H:%M:%S").date()
            except ValueError:
                try:
                    # Try parsing as date only
                    last_paid = datetime.strptime(str(last_paid_date), "%Y-%m-%d").date()
                except ValueError:
                    # If both fail, try to extract just the date part
                    last_paid = datetime.strptime(str(last_paid_date).split()[0], "%Y-%m-%d").date()
            last_month_date = last_paid
        else:
            # Calculate previous month
            if current_month == 1:
                prev_month = 12
                prev_year = current_year - 1
            else:
                prev_month = current_month - 1
                prev_year = current_year
            
            try:
                last_month_date = datetime(prev_year, prev_month, int(payment_day)).date()
            except ValueError:
                last_day = (datetime(prev_year, prev_month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                last_month_date = last_day
        
        # Calculate next month's payment date
        if current_month == 12:
            next_month = 1
            next_year = current_year + 1
        else:
            next_month = current_month + 1
            next_year = current_year
        
        try:
            next_month_date = datetime(next_year, next_month, int(payment_day)).date()
        except ValueError:
            last_day = (datetime(next_year, next_month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            next_month_date = last_day
        
        return last_month_date, this_month_date, next_month_date
    
    def add_recurring_payment(self):
        dialog = PaymentDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['name']:
                QMessageBox.warning(self, "Error", "Please enter a payment name.")
                return
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            today = datetime.today().date()
            # Set period_start_date to current month's first day
            period_start = datetime(today.year, today.month, 1).date()
            
            cursor.execute(
                """INSERT INTO recurring_payments (name, amount, payment_day, payment_type, pay_period_months, period_start_date, is_active) 
                   VALUES (?, ?, ?, ?, ?, ?, 1)""",
                (data['name'], data['amount'], data['payment_day'], data['payment_type'], 
                 data['pay_period_months'], period_start)
            )
            conn.commit()
            conn.close()
            
            self.load_recurring_payments()
            QMessageBox.information(self, "Success", "Recurring payment added successfully.")
    
    def edit_recurring_payment(self):
        row = self.recurring_payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a payment to edit.")
            return
        
        payment_id = int(self.recurring_payments_table.item(row, 0).text())
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, amount, payment_day, 
                   COALESCE(payment_type, 'debit') as payment_type,
                   last_paid_date, created_at,
                   pay_period_months, period_start_date
            FROM recurring_payments WHERE id = ?
        """, (payment_id,))
        payment = cursor.fetchone()
        conn.close()
        
        if payment:
            dialog = PaymentDialog(self, payment)
            if dialog.exec():
                data = dialog.get_data()
                if not data['name']:
                    QMessageBox.warning(self, "Error", "Please enter a payment name.")
                    return
                
                conn = self.db.get_connection()
                cursor = conn.cursor()
                # If pay_period_months is being changed, update period_start_date to current month
                today = datetime.today().date()
                new_period_start = datetime(today.year, today.month, 1).date()
                
                cursor.execute(
                    """UPDATE recurring_payments 
                       SET name = ?, amount = ?, payment_day = ?, payment_type = ?, 
                           pay_period_months = ?, period_start_date = ? 
                       WHERE id = ?""",
                    (data['name'], data['amount'], data['payment_day'], data['payment_type'], 
                     data['pay_period_months'], new_period_start, payment_id)
                )
                conn.commit()
                conn.close()
                
                self.load_recurring_payments()
                QMessageBox.information(self, "Success", "Recurring payment updated successfully.")
    
    def delete_recurring_payment(self):
        row = self.recurring_payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a payment to delete.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Delete", "Are you sure you want to delete this payment?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            payment_id = int(self.recurring_payments_table.item(row, 0).text())
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM recurring_payments WHERE id = ?", (payment_id,))
            conn.commit()
            conn.close()
            
            self.load_recurring_payments()
            QMessageBox.information(self, "Success", "Payment deleted successfully.")
    
    def mark_delete_next_month(self):
        """Mark or unmark a payment for deletion next month"""
        row = self.recurring_payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a payment to mark for deletion next month.")
            return
        
        payment_id = int(self.recurring_payments_table.item(row, 0).text())
        payment_name = self.recurring_payments_table.item(row, 1).text()
        
        # Check current status
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT delete_next_month FROM recurring_payments WHERE id = ?", (payment_id,))
        result = cursor.fetchone()
        is_marked = result and result[0] == 1
        
        if is_marked:
            # Unmark for deletion
            reply = QMessageBox.question(
                self, "Unmark Delete Next Month", 
                f"Unmark '{payment_name}' for deletion?\n\nThis payment will no longer be deleted next month.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                cursor.execute("UPDATE recurring_payments SET delete_next_month = 0 WHERE id = ?", (payment_id,))
                conn.commit()
                conn.close()
                
                self.load_recurring_payments()
                QMessageBox.information(self, "Success", f"'{payment_name}' will no longer be deleted next month.")
            else:
                conn.close()
        else:
            # Mark for deletion
            reply = QMessageBox.question(
                self, "Confirm Delete Next Month", 
                f"Mark '{payment_name}' for deletion next month?\n\nThis payment will be automatically deleted when the next month starts.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                cursor.execute("UPDATE recurring_payments SET delete_next_month = 1 WHERE id = ?", (payment_id,))
                conn.commit()
                conn.close()
                
                self.load_recurring_payments()
                QMessageBox.information(self, "Success", f"'{payment_name}' will be deleted next month.")
            else:
                conn.close()
    
    def check_and_delete_pending_deletions(self):
        """Check if it's a new month and delete payments marked for deletion"""
        today = datetime.today().date()
        current_month = today.month
        current_year = today.year
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get the last month we checked for deletions
        cursor.execute("""
            SELECT value FROM app_settings WHERE key = 'last_deletion_check_month'
        """)
        result = cursor.fetchone()
        
        last_check_month = None
        last_check_year = None
        
        if result:
            try:
                # Format: "YYYY-MM"
                parts = result[0].split('-')
                last_check_year = int(parts[0])
                last_check_month = int(parts[1])
            except:
                pass
        
        # Check if we're in a new month compared to last check
        is_new_month = False
        if last_check_month is None or last_check_year is None:
            # First time running, don't delete yet
            is_new_month = False
        elif current_year > last_check_year or (current_year == last_check_year and current_month > last_check_month):
            # New month detected
            is_new_month = True
        
        # Update the last check date
        cursor.execute("""
            INSERT OR REPLACE INTO app_settings (key, value, updated_at)
            VALUES ('last_deletion_check_month', ?, CURRENT_TIMESTAMP)
        """, (f"{current_year}-{current_month:02d}",))
        
        # Only delete if we're in a new month
        if is_new_month:
            cursor.execute("""
                SELECT id, name FROM recurring_payments 
                WHERE delete_next_month = 1
            """)
            pending_deletions = cursor.fetchall()
            
            if pending_deletions:
                deleted_count = 0
                deleted_names = []
                
                for payment_id, payment_name in pending_deletions:
                    # Delete the payment
                    cursor.execute("DELETE FROM recurring_payments WHERE id = ?", (payment_id,))
                    deleted_count += 1
                    deleted_names.append(payment_name)
                
                if deleted_count > 0:
                    conn.commit()
                    conn.close()
                    
                    # Show notification
                    names_list = "\n".join([f"• {name}" for name in deleted_names])
                    QMessageBox.information(
                        self, 
                        "Payments Deleted", 
                        f"New month detected! The following {deleted_count} payment(s) marked for deletion have been removed:\n\n{names_list}"
                    )
                    
                    # Reload the table
                    self.load_recurring_payments()
                    return True
        
        conn.commit()
        conn.close()
        return False
    
    def check_and_disable_expired_payments(self):
        """Check for payments that have exceeded their pay period and disable them"""
        today = datetime.today().date()
        current_month = today.month
        current_year = today.year
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get all active payments with pay periods
        cursor.execute("""
            SELECT id, name, pay_period_months, period_start_date 
            FROM recurring_payments 
            WHERE is_active = 1 
            AND pay_period_months IS NOT NULL 
            AND pay_period_months != -1
        """)
        payments_with_periods = cursor.fetchall()
        
        expired_count = 0
        expired_names = []
        
        for payment_id, name, pay_period_months, period_start_date in payments_with_periods:
            if period_start_date:
                try:
                    if isinstance(period_start_date, str):
                        try:
                            start_date = datetime.strptime(period_start_date, "%Y-%m-%d %H:%M:%S").date()
                        except ValueError:
                            start_date = datetime.strptime(period_start_date, "%Y-%m-%d").date()
                    else:
                        start_date = period_start_date
                    
                    # Calculate months elapsed
                    months_elapsed = (current_year - start_date.year) * 12 + (current_month - start_date.month)
                    
                    # Check if period has expired
                    if months_elapsed >= pay_period_months:
                        # Disable the payment
                        cursor.execute(
                            "UPDATE recurring_payments SET is_active = 0 WHERE id = ?",
                            (payment_id,)
                        )
                        expired_count += 1
                        expired_names.append(name)
                except Exception as e:
                    print(f"Error checking payment {name}: {e}")
                    continue
        
        if expired_count > 0:
            conn.commit()
            conn.close()
            
            # Show notification
            names_list = "\n".join([f"• {name}" for name in expired_names])
            QMessageBox.information(
                self,
                "Payments Expired",
                f"The following {expired_count} payment(s) have reached the end of their pay period and have been disabled:\n\n{names_list}"
            )
            
            # Reload the table
            self.load_recurring_payments()
            return True
        
        conn.commit()
        conn.close()
        return False
    
    def mark_recurring_payment_paid(self):
        row = self.recurring_payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a payment to mark as paid.")
            return
        
        payment_id = int(self.recurring_payments_table.item(row, 0).text())
        payment_name = self.recurring_payments_table.item(row, 1).text()
        amount = float(self.recurring_payments_table.item(row, 2).text().replace('£', '').replace(',', ''))
        
        today = datetime.today().date()
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Store old last_paid_date for undo
            cursor.execute("SELECT last_paid_date FROM recurring_payments WHERE id = ?", (payment_id,))
            old_last_paid = cursor.fetchone()[0]
            
            # Update last paid date
            cursor.execute(
                "UPDATE recurring_payments SET last_paid_date = ? WHERE id = ?",
                (today.strftime("%Y-%m-%d"), payment_id)
            )
            
            # Add to payment history
            cursor.execute(
                """INSERT INTO payment_history (payment_id, payment_type, name, amount, payment_date, month, year)
                   VALUES (?, 'recurring', ?, ?, ?, ?, ?)""",
                (payment_id, payment_name, amount, today.strftime("%Y-%m-%d"), today.month, today.year)
            )
            
            history_id = cursor.lastrowid
            
            # Store in recent_transactions for undo
            cursor.execute(
                """INSERT INTO recent_transactions 
                   (history_id, payment_id, payment_type, name, amount, payment_date, month, year, action_type, old_last_paid_date)
                   VALUES (?, ?, 'recurring', ?, ?, ?, ?, ?, 'mark_paid', ?)""",
                (history_id, payment_id, payment_name, amount, today.strftime("%Y-%m-%d"), today.month, today.year, old_last_paid)
            )
            
            # Store old last_paid_date in a separate column (we'll use a text field in the table)
            # For now, we'll just store it in memory or use a temp approach
            
            conn.commit()
            conn.close()
            
            # Update monthly summary (with connection closed)
            self.update_monthly_summary(today.month, today.year)
            
            self.load_recurring_payments()
            self.load_history()
            self.load_summary()  # Refresh summary tab
            QMessageBox.information(self, "Success", f"Payment '{payment_name}' marked as paid.")
        except Exception as e:
            conn.rollback()
            conn.close()
            QMessageBox.critical(self, "Error", f"Failed to mark payment as paid: {str(e)}")
    
    def update_payment_dates(self):
        """Update payment dates based on current month"""
        self.load_recurring_payments()
        self.load_one_time_payments()
    
    def detect_payments(self):
        """Detect payments that have passed their due date and mark them as paid"""
        today = datetime.today().date()
        current_month = today.month
        current_year = today.year
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        detected_count = 0
        detected_payments = []
        
        try:
            # Check recurring payments
            cursor.execute("SELECT id, name, amount, payment_day, last_paid_date FROM recurring_payments WHERE COALESCE(is_active, 1) = 1")
            recurring_payments = cursor.fetchall()
            
            for payment_id, name, amount, payment_day, last_paid_date in recurring_payments:
                # Calculate this month's payment date
                try:
                    this_month_date = datetime(current_year, current_month, int(payment_day)).date()
                except ValueError:
                    # Handle day 31 in months with fewer days
                    last_day = (datetime(current_year, current_month, 1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                    this_month_date = last_day
                
                # Check if payment date has passed and hasn't been paid this month
                if this_month_date <= today:
                    # Check if already paid this month
                    if last_paid_date:
                        # Handle both date-only and datetime strings
                        try:
                            last_paid = datetime.strptime(str(last_paid_date), "%Y-%m-%d %H:%M:%S").date()
                        except ValueError:
                            try:
                                last_paid = datetime.strptime(str(last_paid_date), "%Y-%m-%d").date()
                            except ValueError:
                                last_paid = datetime.strptime(str(last_paid_date).split()[0], "%Y-%m-%d").date()
                        # If last paid date is in the same month and year, skip
                        if last_paid.month == current_month and last_paid.year == current_year:
                            continue
                    
                    # Check if there's already a payment history entry for this month
                    cursor.execute("""
                        SELECT COUNT(*) FROM payment_history
                        WHERE payment_id = ? AND payment_type = 'recurring'
                        AND month = ? AND year = ?
                    """, (payment_id, current_month, current_year))
                    
                    if cursor.fetchone()[0] == 0:
                        # Mark as paid
                        detected_payments.append(('recurring', payment_id, name, amount, this_month_date))
                        detected_count += 1
            
            # Check one-time payments
            cursor.execute("""
                SELECT id, name, amount, payment_date, paid
                FROM one_time_payments
                WHERE paid = 0 AND payment_date <= ?
            """, (today.strftime("%Y-%m-%d"),))
            
            one_time_payments = cursor.fetchall()
            
            for payment_id, name, amount, payment_date_str, paid in one_time_payments:
                payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
                
                # Check if there's already a payment history entry
                cursor.execute("""
                    SELECT COUNT(*) FROM payment_history
                    WHERE payment_id = ? AND payment_type = 'one_time'
                    AND payment_date = ?
                """, (payment_id, payment_date_str))
                
                if cursor.fetchone()[0] == 0:
                    detected_payments.append(('one_time', payment_id, name, amount, payment_date))
                    detected_count += 1
            
            conn.close()
            
            if detected_count == 0:
                QMessageBox.information(self, "No Payments Detected", 
                    "No payments found that have passed their due date and haven't been marked as paid.")
                return
            
            # Ask user if they want to mark all detected payments as paid
            payment_list = "\n".join([f"• {name}: £{amount:,.2f} ({ptype})" for ptype, _, name, amount, _ in detected_payments])
            
            reply = QMessageBox.question(
                self, "Detect Payments",
                f"Found {detected_count} payment(s) that have passed their due date:\n\n{payment_list}\n\n"
                "Would you like to mark all of these as paid?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                # Mark all detected payments as paid
                conn = self.db.get_connection()
                cursor = conn.cursor()
                
                # Track which months need summary updates (to avoid duplicate updates)
                months_to_update = set()
                
                try:
                    for ptype, payment_id, name, amount, payment_date in detected_payments:
                        try:
                            if ptype == 'recurring':
                                # Store old last_paid_date for undo
                                cursor.execute("SELECT last_paid_date FROM recurring_payments WHERE id = ?", (payment_id,))
                                old_last_paid = cursor.fetchone()[0]
                                
                                # Update last paid date
                                cursor.execute(
                                    "UPDATE recurring_payments SET last_paid_date = ? WHERE id = ?",
                                    (today.strftime("%Y-%m-%d"), payment_id)
                                )
                                
                                # Add to payment history (using current amount - this preserves historical records)
                                cursor.execute(
                                    """INSERT INTO payment_history (payment_id, payment_type, name, amount, payment_date, month, year)
                                       VALUES (?, 'recurring', ?, ?, ?, ?, ?)""",
                                    (payment_id, name, amount, today.strftime("%Y-%m-%d"), today.month, today.year)
                                )
                                
                                history_id = cursor.lastrowid
                                
                                # Store in recent_transactions for undo
                                cursor.execute(
                                    """INSERT INTO recent_transactions 
                                       (history_id, payment_id, payment_type, name, amount, payment_date, month, year, action_type, old_last_paid_date)
                                       VALUES (?, ?, 'recurring', ?, ?, ?, ?, ?, 'mark_paid', ?)""",
                                    (history_id, payment_id, name, amount, today.strftime("%Y-%m-%d"), today.month, today.year, old_last_paid)
                                )
                                
                                months_to_update.add((today.month, today.year))
                                
                            elif ptype == 'one_time':
                                # Update paid status
                                cursor.execute("UPDATE one_time_payments SET paid = 1 WHERE id = ?", (payment_id,))
                                
                                # Add to payment history
                                cursor.execute(
                                    """INSERT INTO payment_history (payment_id, payment_type, name, amount, payment_date, month, year)
                                       VALUES (?, 'one_time', ?, ?, ?, ?, ?)""",
                                    (payment_id, name, amount, payment_date.strftime("%Y-%m-%d"), payment_date.month, payment_date.year)
                                )
                                
                                history_id = cursor.lastrowid
                                
                                # Store in recent_transactions for undo
                                cursor.execute(
                                    """INSERT INTO recent_transactions 
                                       (history_id, payment_id, payment_type, name, amount, payment_date, month, year, action_type, old_last_paid_date)
                                       VALUES (?, ?, 'one_time', ?, ?, ?, ?, ?, 'mark_paid', NULL)""",
                                    (history_id, payment_id, name, amount, payment_date.strftime("%Y-%m-%d"), payment_date.month, payment_date.year)
                                )
                                
                                months_to_update.add((payment_date.month, payment_date.year))
                        
                        except Exception as e:
                            print(f"Error processing payment {name}: {e}")
                            continue
                    
                    conn.commit()
                    conn.close()
                    
                    # Update monthly summaries AFTER closing the main connection
                    for month, year in months_to_update:
                        self.update_monthly_summary(month, year)
                    
                    # Refresh all tables
                    self.load_recurring_payments()
                    self.load_one_time_payments()
                    self.load_history()
                    self.load_summary()  # Refresh summary tab
                    
                    QMessageBox.information(self, "Success", 
                        f"Successfully marked {detected_count} payment(s) as paid.")
                
                except Exception as e:
                    conn.rollback()
                    conn.close()
                    QMessageBox.critical(self, "Error", f"Failed to mark payments as paid: {str(e)}")
        
        except Exception as e:
            if conn:
                conn.rollback()
                conn.close()
            QMessageBox.critical(self, "Error", f"Failed to detect payments: {str(e)}")
    
    def undo_last_payment(self):
        """Undo the last payment/income transaction"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get the most recent transaction
            cursor.execute("""
                SELECT id, history_id, payment_id, payment_type, name, amount, 
                       payment_date, month, year, action_type, old_last_paid_date
                FROM recent_transactions
                ORDER BY created_at DESC
                LIMIT 1
            """)
            
            transaction = cursor.fetchone()
            
            if not transaction:
                QMessageBox.information(self, "No Transaction", "No recent transaction to undo.")
                conn.close()
                return
            
            trans_id, history_id, payment_id, payment_type, name, amount, payment_date, month, year, action_type, old_last_paid_date = transaction
            
            # Confirm undo
            reply = QMessageBox.question(
                self, "Confirm Undo", 
                f"Are you sure you want to undo the last transaction?\n\n{name}: £{amount:,.2f} ({payment_type})",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            
            if reply != QMessageBox.StandardButton.Yes:
                conn.close()
                return
            
            # Delete from payment_history
            cursor.execute("DELETE FROM payment_history WHERE id = ?", (history_id,))
            
            # Restore old state based on payment type
            if payment_type == 'recurring' and action_type == 'mark_paid':
                # Restore old last_paid_date
                cursor.execute(
                    "UPDATE recurring_payments SET last_paid_date = ? WHERE id = ?",
                    (old_last_paid_date, payment_id)
                )
            elif payment_type == 'income' and action_type == 'mark_received':
                # Restore old last_received_date
                cursor.execute(
                    "UPDATE recurring_income SET last_received_date = ? WHERE id = ?",
                    (old_last_paid_date, payment_id)
                )
            elif payment_type == 'one_time' and action_type == 'mark_paid':
                # Restore paid status to 0
                cursor.execute("UPDATE one_time_payments SET paid = 0 WHERE id = ?", (payment_id,))
            
            # Remove from recent_transactions
            cursor.execute("DELETE FROM recent_transactions WHERE id = ?", (trans_id,))
            
            conn.commit()
            conn.close()
            
            # Update monthly summary
            self.update_monthly_summary(month, year)
            
            # Refresh all tables
            self.load_recurring_payments()
            self.load_recurring_income()
            self.load_one_time_payments()
            self.load_history()
            self.load_summary()  # Refresh summary tab
            
            QMessageBox.information(self, "Success", f"Transaction '{name}' has been undone.")
            
        except Exception as e:
            conn.rollback()
            conn.close()
            QMessageBox.critical(self, "Error", f"Failed to undo transaction: {str(e)}")
    
    # Database operations for recurring income
    def load_recurring_income(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recurring_income ORDER BY name")
        income_list = cursor.fetchall()
        conn.close()
        
        self.recurring_income_table.setRowCount(len(income_list))
        
        for row_idx, income in enumerate(income_list):
            income_id, name, amount, income_day, last_received_date, created_at = income
            
            self.recurring_income_table.setItem(row_idx, 0, QTableWidgetItem(str(income_id)))
            self.recurring_income_table.setItem(row_idx, 1, QTableWidgetItem(name))
            self.recurring_income_table.setItem(row_idx, 2, QTableWidgetItem(f"£{amount:,.2f}"))
            self.recurring_income_table.setItem(row_idx, 3, QTableWidgetItem(f"Day {int(income_day)}"))
            
            if last_received_date:
                # Handle both date-only and datetime strings
                try:
                    date = datetime.strptime(str(last_received_date), "%Y-%m-%d %H:%M:%S").date()
                except ValueError:
                    try:
                        date = datetime.strptime(str(last_received_date), "%Y-%m-%d").date()
                    except ValueError:
                        date = datetime.strptime(str(last_received_date).split()[0], "%Y-%m-%d").date()
                self.recurring_income_table.setItem(row_idx, 4, QTableWidgetItem(date.strftime("%d/%m/%Y")))
            else:
                self.recurring_income_table.setItem(row_idx, 4, QTableWidgetItem("Never"))
    
    def add_recurring_income(self):
        dialog = IncomeDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['name']:
                QMessageBox.warning(self, "Error", "Please enter an income name.")
                return
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO recurring_income (name, amount, income_day) VALUES (?, ?, ?)",
                (data['name'], data['amount'], data['income_day'])
            )
            conn.commit()
            conn.close()
            
            self.load_recurring_income()
            QMessageBox.information(self, "Success", "Recurring income added successfully.")
    
    def edit_recurring_income(self):
        row = self.recurring_income_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select an income to edit.")
            return
        
        income_id = int(self.recurring_income_table.item(row, 0).text())
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM recurring_income WHERE id = ?", (income_id,))
        income = cursor.fetchone()
        conn.close()
        
        if income:
            dialog = IncomeDialog(self, income)
            if dialog.exec():
                data = dialog.get_data()
                if not data['name']:
                    QMessageBox.warning(self, "Error", "Please enter an income name.")
                    return
                
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE recurring_income SET name = ?, amount = ?, income_day = ? WHERE id = ?",
                    (data['name'], data['amount'], data['income_day'], income_id)
                )
                conn.commit()
                conn.close()
                
                self.load_recurring_income()
                QMessageBox.information(self, "Success", "Recurring income updated successfully.")
    
    def delete_recurring_income(self):
        row = self.recurring_income_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select an income to delete.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Delete", "Are you sure you want to delete this income?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            income_id = int(self.recurring_income_table.item(row, 0).text())
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM recurring_income WHERE id = ?", (income_id,))
            conn.commit()
            conn.close()
            
            self.load_recurring_income()
            QMessageBox.information(self, "Success", "Income deleted successfully.")
    
    def mark_recurring_income_received(self):
        row = self.recurring_income_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select an income to mark as received.")
            return
        
        income_id = int(self.recurring_income_table.item(row, 0).text())
        income_name = self.recurring_income_table.item(row, 1).text()
        amount = float(self.recurring_income_table.item(row, 2).text().replace('£', '').replace(',', ''))
        
        today = datetime.today().date()
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Store old last_received_date for undo
            cursor.execute("SELECT last_received_date FROM recurring_income WHERE id = ?", (income_id,))
            old_last_received = cursor.fetchone()[0]
            
            # Update last received date
            cursor.execute(
                "UPDATE recurring_income SET last_received_date = ? WHERE id = ?",
                (today.strftime("%Y-%m-%d"), income_id)
            )
            
            # Add to payment history (as income)
            cursor.execute(
                """INSERT INTO payment_history (payment_id, payment_type, name, amount, payment_date, month, year)
                   VALUES (?, 'income', ?, ?, ?, ?, ?)""",
                (income_id, income_name, amount, today.strftime("%Y-%m-%d"), today.month, today.year)
            )
            
            history_id = cursor.lastrowid
            
            # Store in recent_transactions for undo
            cursor.execute(
                """INSERT INTO recent_transactions 
                   (history_id, payment_id, payment_type, name, amount, payment_date, month, year, action_type, old_last_paid_date)
                   VALUES (?, ?, 'income', ?, ?, ?, ?, ?, 'mark_received', ?)""",
                (history_id, income_id, income_name, amount, today.strftime("%Y-%m-%d"), today.month, today.year, old_last_received)
            )
            
            conn.commit()
            conn.close()
            
            # Update monthly summary (with connection closed)
            self.update_monthly_summary(today.month, today.year)
            
            self.load_recurring_income()
            self.load_history()
            self.load_summary()  # Refresh summary tab
            QMessageBox.information(self, "Success", f"Income '{income_name}' marked as received.")
        except Exception as e:
            conn.rollback()
            conn.close()
            QMessageBox.critical(self, "Error", f"Failed to mark income as received: {str(e)}")
    
    # Database operations for one-time payments
    def load_one_time_payments(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        today = datetime.today().date()
        current_month = today.month
        current_year = today.year
        
        # Get payments for current month or future
        cursor.execute("""
            SELECT * FROM one_time_payments 
            WHERE payment_date >= date('now', 'start of month')
            OR (strftime('%m', payment_date) = ? AND strftime('%Y', payment_date) = ?)
            ORDER BY payment_date
        """, (f"{current_month:02d}", str(current_year)))
        payments = cursor.fetchall()
        conn.close()
        
        self.one_time_payments_table.setRowCount(len(payments))
        
        for row_idx, payment in enumerate(payments):
            payment_id, name, amount, payment_date, paid, created_at = payment
            date = datetime.strptime(payment_date, "%Y-%m-%d").date()
            
            self.one_time_payments_table.setItem(row_idx, 0, QTableWidgetItem(str(payment_id)))
            self.one_time_payments_table.setItem(row_idx, 1, QTableWidgetItem(name))
            self.one_time_payments_table.setItem(row_idx, 2, QTableWidgetItem(f"£{amount:,.2f}"))
            self.one_time_payments_table.setItem(row_idx, 3, QTableWidgetItem(date.strftime("%d/%m/%Y")))
            
            status_item = QTableWidgetItem("✅ Paid" if paid else "❌ Unpaid")
            if date <= today and not paid:
                status_item.setForeground(Qt.GlobalColor.yellow)  # Overdue
            self.one_time_payments_table.setItem(row_idx, 4, status_item)
    
    def add_one_time_payment(self):
        dialog = OneTimePaymentDialog(self)
        if dialog.exec():
            data = dialog.get_data()
            if not data['name']:
                QMessageBox.warning(self, "Error", "Please enter a payment name.")
                return
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO one_time_payments (name, amount, payment_date) VALUES (?, ?, ?)",
                (data['name'], data['amount'], data['payment_date'])
            )
            conn.commit()
            conn.close()
            
            self.load_one_time_payments()
            QMessageBox.information(self, "Success", "One-time payment added successfully.")
    
    def edit_one_time_payment(self):
        row = self.one_time_payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a payment to edit.")
            return
        
        payment_id = int(self.one_time_payments_table.item(row, 0).text())
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM one_time_payments WHERE id = ?", (payment_id,))
        payment = cursor.fetchone()
        conn.close()
        
        if payment:
            dialog = OneTimePaymentDialog(self, payment)
            if dialog.exec():
                data = dialog.get_data()
                if not data['name']:
                    QMessageBox.warning(self, "Error", "Please enter a payment name.")
                    return
                
                conn = self.db.get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE one_time_payments SET name = ?, amount = ?, payment_date = ? WHERE id = ?",
                    (data['name'], data['amount'], data['payment_date'], payment_id)
                )
                conn.commit()
                conn.close()
                
                self.load_one_time_payments()
                QMessageBox.information(self, "Success", "One-time payment updated successfully.")
    
    def delete_one_time_payment(self):
        row = self.one_time_payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a payment to delete.")
            return
        
        reply = QMessageBox.question(
            self, "Confirm Delete", "Are you sure you want to delete this payment?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            payment_id = int(self.one_time_payments_table.item(row, 0).text())
            
            conn = self.db.get_connection()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM one_time_payments WHERE id = ?", (payment_id,))
            conn.commit()
            conn.close()
            
            self.load_one_time_payments()
            QMessageBox.information(self, "Success", "Payment deleted successfully.")
    
    def mark_one_time_payment_paid(self):
        row = self.one_time_payments_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a payment to mark as paid.")
            return
        
        payment_id = int(self.one_time_payments_table.item(row, 0).text())
        payment_name = self.one_time_payments_table.item(row, 1).text()
        amount = float(self.one_time_payments_table.item(row, 2).text().replace('£', '').replace(',', ''))
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("SELECT payment_date, paid FROM one_time_payments WHERE id = ?", (payment_id,))
            result = cursor.fetchone()
            payment_date = datetime.strptime(result[0], "%Y-%m-%d").date()
            was_paid = result[1]
            
            if was_paid:
                QMessageBox.warning(self, "Already Paid", "This payment is already marked as paid.")
                conn.close()
                return
            
            # Update paid status
            cursor.execute("UPDATE one_time_payments SET paid = 1 WHERE id = ?", (payment_id,))
            
            # Add to payment history
            cursor.execute(
                """INSERT INTO payment_history (payment_id, payment_type, name, amount, payment_date, month, year)
                   VALUES (?, 'one_time', ?, ?, ?, ?, ?)""",
                (payment_id, payment_name, amount, payment_date.strftime("%Y-%m-%d"), payment_date.month, payment_date.year)
            )
            
            history_id = cursor.lastrowid
            
            # Store in recent_transactions for undo
            cursor.execute(
                """INSERT INTO recent_transactions 
                   (history_id, payment_id, payment_type, name, amount, payment_date, month, year, action_type, old_last_paid_date)
                   VALUES (?, ?, 'one_time', ?, ?, ?, ?, ?, 'mark_paid', NULL)""",
                (history_id, payment_id, payment_name, amount, payment_date.strftime("%Y-%m-%d"), payment_date.month, payment_date.year)
            )
            
            conn.commit()
            conn.close()
            
            # Update monthly summary (with connection closed)
            self.update_monthly_summary(payment_date.month, payment_date.year)
            
            self.load_one_time_payments()
            self.load_history()
            self.load_summary()  # Refresh summary tab
            QMessageBox.information(self, "Success", f"Payment '{payment_name}' marked as paid.")
        except Exception as e:
            conn.rollback()
            conn.close()
            QMessageBox.critical(self, "Error", f"Failed to mark payment as paid: {str(e)}")
    
    # History and summary operations
    def load_history(self):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Get current month summary
        today = datetime.today().date()
        current_month = today.month
        current_year = today.year
        
        # First, ensure current month summary is up to date
        # Close connection before calling update_monthly_summary to avoid locks
        conn.close()
        self.update_monthly_summary(current_month, current_year)
        
        # Reopen connection to get updated values
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        # Now get the updated values from monthly_summary
        cursor.execute("""
            SELECT total_payments, total_income, savings_amount, net_savings
            FROM monthly_summary
            WHERE month = ? AND year = ?
        """, (current_month, current_year))
        
        summary_result = cursor.fetchone()
        if summary_result:
            total_payments, total_income, savings, net_savings = summary_result
            total_payments = total_payments if total_payments else 0
            total_income = total_income if total_income else 0
            savings = savings if savings else 0
            net_savings = net_savings if net_savings else 0
        else:
            # Fallback: calculate from payment_history if no summary exists
            cursor.execute("""
                SELECT 
                    COALESCE(SUM(CASE WHEN payment_type IN ('recurring', 'one_time') THEN amount ELSE 0 END), 0) as total_payments
                FROM payment_history
                WHERE month = ? AND year = ?
            """, (current_month, current_year))
            result = cursor.fetchone()
            total_payments = result[0] if result[0] else 0
            
            # For current month, use total scheduled recurring income
            cursor.execute("SELECT amount FROM recurring_income")
            recurring_income_list = cursor.fetchall()
            total_income = sum(income[0] for income in recurring_income_list) if recurring_income_list else 0
            
            savings = 0
            net_savings = total_income - total_payments - savings
        
        # Update summary label
        self.summary_label.setText(f"""
            <b>Current Month ({datetime(current_year, current_month, 1).strftime('%B %Y')}):</b><br>
            Total Payments: £{total_payments:,.2f}<br>
            Total Income: £{total_income:,.2f}<br>
            Savings: £{savings:,.2f}<br>
            <b>Net Savings: £{net_savings:,.2f}</b>
        """)
        
        self.savings_input.setValue(savings)
        
        # Load all monthly summaries
        cursor.execute("""
            SELECT month, year, total_payments, total_income, savings_amount, net_savings
            FROM monthly_summary
            ORDER BY year DESC, month DESC
        """)
        summaries = cursor.fetchall()
        conn.close()
        
        # Clear existing table and buttons
        self.history_table.setRowCount(0)
        self.history_table.setRowCount(len(summaries))
        
        for row_idx, summary in enumerate(summaries):
            month, year, payments, income, savings, net = summary
            month_name = datetime(year, month, 1).strftime("%B %Y")
            
            self.history_table.setItem(row_idx, 0, QTableWidgetItem(month_name))
            self.history_table.setItem(row_idx, 1, QTableWidgetItem(f"£{payments:,.2f}"))
            self.history_table.setItem(row_idx, 2, QTableWidgetItem(f"£{income:,.2f}"))
            self.history_table.setItem(row_idx, 3, QTableWidgetItem(f"£{savings:,.2f}"))
            
            net_item = QTableWidgetItem(f"£{net:,.2f}")
            if net < 0:
                net_item.setForeground(Qt.GlobalColor.red)
            else:
                net_item.setForeground(Qt.GlobalColor.green)
            self.history_table.setItem(row_idx, 4, net_item)
            
            # View details button - use a closure to capture month and year correctly
            def make_view_handler(m, y):
                return lambda: self.view_month_details(m, y)
            view_btn = QPushButton("View Details")
            view_btn.clicked.connect(make_view_handler(month, year))
            self.history_table.setCellWidget(row_idx, 5, view_btn)
    
    def refresh_history(self):
        """Refresh history by recalculating all monthly summaries from payment history"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get all unique month/year combinations from payment_history
            cursor.execute("""
                SELECT DISTINCT month, year 
                FROM payment_history
                ORDER BY year DESC, month DESC
            """)
            months_from_history = cursor.fetchall()
            
            # Also get all months from monthly_summary (to preserve savings amounts)
            cursor.execute("""
                SELECT DISTINCT month, year 
                FROM monthly_summary
                ORDER BY year DESC, month DESC
            """)
            months_from_summary = cursor.fetchall()
            
            # Store savings amounts before recalculating to preserve them
            savings_map = {}
            for month, year in months_from_summary:
                cursor.execute("""
                    SELECT savings_amount FROM monthly_summary
                    WHERE month = ? AND year = ?
                """, (month, year))
                result = cursor.fetchone()
                if result and result[0]:
                    savings_map[(month, year)] = result[0]
            
            # Combine and get unique months
            all_months = set(months_from_history + months_from_summary)
            
            # Always include current month
            today = datetime.today().date()
            all_months.add((today.month, today.year))
            
            conn.close()
            
            if not all_months:
                QMessageBox.information(self, "No History", "No payment history found to refresh.")
                return
            
            # Recalculate monthly summaries for each month
            # This will preserve savings amounts from the map
            updated_count = 0
            for month, year in sorted(all_months, key=lambda x: (x[1], x[0]), reverse=True):
                # Temporarily set savings in monthly_summary if it exists in our map
                if (month, year) in savings_map:
                    temp_conn = self.db.get_connection()
                    temp_cursor = temp_conn.cursor()
                    temp_cursor.execute("""
                        INSERT OR REPLACE INTO monthly_summary (month, year, savings_amount, updated_at)
                        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                    """, (month, year, savings_map[(month, year)]))
                    temp_conn.commit()
                    temp_conn.close()
                
                # Now update the summary (this will recalculate payments/income but preserve savings)
                self.update_monthly_summary(month, year)
                updated_count += 1
            
            # Reload history table and summary
            self.load_history()
            
            # Also refresh summary tab to show updated data
            self.load_summary()
            
            QMessageBox.information(self, "History Refreshed", 
                f"Successfully refreshed history for {updated_count} month(s).")
        
        except Exception as e:
            if conn:
                conn.close()
            QMessageBox.critical(self, "Error", f"Failed to refresh history: {str(e)}")
    
    def save_current_month_savings(self):
        today = datetime.today().date()
        savings_amount = self.savings_input.value()
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Update or insert monthly summary
            cursor.execute("""
                INSERT OR REPLACE INTO monthly_summary (month, year, savings_amount, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (today.month, today.year, savings_amount))
            
            conn.commit()
            conn.close()
            
            # Recalculate net savings AFTER closing connection
            self.update_monthly_summary(today.month, today.year)
            
            self.load_history()
            QMessageBox.information(self, "Success", f"Savings amount saved for {today.strftime('%B %Y')}.")
        except Exception as e:
            conn.rollback()
            conn.close()
            QMessageBox.critical(self, "Error", f"Failed to save savings: {str(e)}")
    
    def create_calendar_tab(self):
        """Create calendar view tab showing daily payment and income totals"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # Title
        title_label = QLabel(f"<h1 style='color: #ffffff; text-align: center;'>📅 Financial Calendar</h1>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                stop:0 #667eea, stop:1 #764ba2);
            border-radius: 10px;
            padding: 15px;
            margin-bottom: 10px;
        """)
        layout.addWidget(title_label)
        
        # Calendar and details layout
        calendar_layout = QHBoxLayout()
        
        # Calendar widget
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setStyleSheet("""
            QCalendarWidget {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, 
                    stop:0 #2d3748, stop:1 #1a202c);
                border: 2px solid #4a5568;
                border-radius: 10px;
                color: #ffffff;
            }
            QCalendarWidget QTableView {
                alternate-background-color: #2d3748;
                background-color: #1a202c;
                selection-background-color: #667eea;
            }
            QCalendarWidget QTableView::item {
                padding: 5px;
            }
            QCalendarWidget QHeaderView::section {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                color: #ffffff;
                font-weight: bold;
                padding: 5px;
            }
            QCalendarWidget QSpinBox {
                background: #2d3748;
                color: #ffffff;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 5px;
            }
            QCalendarWidget QToolButton {
                background: #2d3748;
                color: #ffffff;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        
        # Connect calendar signals
        self.calendar.selectionChanged.connect(self.on_calendar_date_selected)
        self.calendar.currentPageChanged.connect(self.on_calendar_month_changed)
        
        calendar_layout.addWidget(self.calendar, 2)
        
        # Details panel
        details_group = QGroupBox("Day Details")
        details_layout = QVBoxLayout()
        
        self.day_details_text = QTextEdit()
        self.day_details_text.setReadOnly(True)
        self.day_details_text.setStyleSheet("""
            QTextEdit {
                background: #1a202c;
                color: #ffffff;
                border: 1px solid #4a5568;
                border-radius: 5px;
                padding: 10px;
                font-size: 12px;
            }
        """)
        details_layout.addWidget(self.day_details_text)
        
        refresh_calendar_btn = QPushButton("🔄 Refresh Calendar")
        refresh_calendar_btn.clicked.connect(self.refresh_calendar)
        refresh_calendar_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #667eea, stop:1 #764ba2);
                color: #ffffff;
                border: none;
                border-radius: 5px;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, 
                    stop:0 #764ba2, stop:1 #667eea);
            }
        """)
        details_layout.addWidget(refresh_calendar_btn)
        
        details_group.setLayout(details_layout)
        calendar_layout.addWidget(details_group, 1)
        
        layout.addLayout(calendar_layout)
        
        # Initialize calendar
        self.refresh_calendar()
        
        widget.setLayout(layout)
        return widget
    
    def refresh_calendar(self):
        """Refresh calendar colors and data"""
        # Get current month/year from calendar
        selected_date = self.calendar.selectedDate()
        current_month = selected_date.month()
        current_year = selected_date.year()
        
        # Calculate daily totals
        daily_totals = self.calculate_daily_totals(current_month, current_year)
        
        # Color code calendar dates
        red_format = QTextCharFormat()
        red_format.setForeground(QColor("#ff6b6b"))
        red_format.setBackground(QColor("#2d1a1a"))
        red_format.setFontWeight(QFont.Weight.Bold)
        
        green_format = QTextCharFormat()
        green_format.setForeground(QColor("#51cf66"))
        green_format.setBackground(QColor("#1a2d1a"))
        green_format.setFontWeight(QFont.Weight.Bold)
        
        mixed_format = QTextCharFormat()
        mixed_format.setForeground(QColor("#ffd43b"))
        mixed_format.setBackground(QColor("#2d2d1a"))
        mixed_format.setFontWeight(QFont.Weight.Bold)
        
        # Reset all dates first
        for day in range(1, 32):
            try:
                date = QDate(current_year, current_month, day)
                if date.isValid():
                    self.calendar.setDateTextFormat(date, QTextCharFormat())
            except:
                pass
        
        # Apply colors based on totals
        for day, totals in daily_totals.items():
            try:
                date = QDate(current_year, current_month, day)
                if date.isValid():
                    outgoing = totals.get('outgoing', 0)
                    incoming = totals.get('incoming', 0)
                    
                    if outgoing > 0 and incoming > 0:
                        self.calendar.setDateTextFormat(date, mixed_format)
                    elif outgoing > 0:
                        self.calendar.setDateTextFormat(date, red_format)
                    elif incoming > 0:
                        self.calendar.setDateTextFormat(date, green_format)
            except:
                pass
        
        # Update details for selected date
        self.on_calendar_date_selected()
    
    def calculate_daily_totals(self, month, year):
        """Calculate total outgoing and incoming amounts for each day in the month"""
        daily_totals = {}
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get all active recurring payments
            cursor.execute("""
                SELECT id, name, amount, payment_day, payment_type
                FROM recurring_payments
                WHERE COALESCE(is_active, 1) = 1
            """)
            recurring_payments = cursor.fetchall()
            
            # Get all one-time payments for this month
            cursor.execute("""
                SELECT name, amount, payment_date
                FROM one_time_payments
                WHERE strftime('%Y-%m', payment_date) = ?
            """, (f"{year}-{month:02d}",))
            one_time_payments = cursor.fetchall()
            
            # Get all recurring income
            cursor.execute("SELECT id, name, amount, income_day FROM recurring_income")
            recurring_income = cursor.fetchall()
            
            # Calculate last day of month
            if month == 12:
                next_month = 1
                next_year = year + 1
            else:
                next_month = month + 1
                next_year = year
            
            last_day = (datetime(next_year, next_month, 1) - timedelta(days=1)).day
            
            # Process recurring payments
            for payment_id, name, amount, payment_day, payment_type in recurring_payments:
                # Calculate payment date for this month
                try:
                    payment_date = datetime(year, month, int(payment_day)).date()
                except ValueError:
                    # Handle day 31 in months with fewer days
                    payment_date = datetime(year, month, last_day).date()
                
                day = payment_date.day
                if day not in daily_totals:
                    daily_totals[day] = {'outgoing': 0, 'incoming': 0, 'details': {'outgoing': [], 'incoming': []}}
                
                # Both debit and credit payments are money going out
                # The distinction is just for tracking purposes (e.g., credit card vs debit card)
                payment_type_label = "Credit" if payment_type == 'credit' else "Debit"
                daily_totals[day]['outgoing'] += amount
                daily_totals[day]['details']['outgoing'].append(f"{name} ({payment_type_label}): £{amount:,.2f}")
            
            # Process one-time payments
            for name, amount, payment_date_str in one_time_payments:
                try:
                    if isinstance(payment_date_str, str):
                        payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
                    else:
                        payment_date = payment_date_str
                    
                    day = payment_date.day
                    if day not in daily_totals:
                        daily_totals[day] = {'outgoing': 0, 'incoming': 0, 'details': {'outgoing': [], 'incoming': []}}
                    
                    daily_totals[day]['outgoing'] += amount
                    daily_totals[day]['details']['outgoing'].append(f"{name} (one-time): £{amount:,.2f}")
                except Exception as e:
                    print(f"Error processing one-time payment: {e}")
                    continue
            
            # Process recurring income
            for income_id, name, amount, income_day in recurring_income:
                # Calculate income date for this month
                try:
                    income_date = datetime(year, month, int(income_day)).date()
                except ValueError:
                    # Handle day 31 in months with fewer days
                    income_date = datetime(year, month, last_day).date()
                
                day = income_date.day
                if day not in daily_totals:
                    daily_totals[day] = {'outgoing': 0, 'incoming': 0, 'details': {'outgoing': [], 'incoming': []}}
                
                daily_totals[day]['incoming'] += amount
                daily_totals[day]['details']['incoming'].append(f"{name}: £{amount:,.2f}")
        
        finally:
            conn.close()
        
        # Calculate running totals for each day
        running_outgoing = 0
        running_incoming = 0
        
        # Calculate last day of month
        if month == 12:
            next_month = 1
            next_year = year + 1
        else:
            next_month = month + 1
            next_year = year
        
        last_day = (datetime(next_year, next_month, 1) - timedelta(days=1)).day
        
        # Process each day from 1 to last_day
        for day in range(1, last_day + 1):
            if day in daily_totals:
                running_outgoing += daily_totals[day]['outgoing']
                running_incoming += daily_totals[day]['incoming']
            
            # Add running totals to each day's data
            if day not in daily_totals:
                daily_totals[day] = {'outgoing': 0, 'incoming': 0, 'details': {'outgoing': [], 'incoming': []}}
            
            daily_totals[day]['running_outgoing'] = running_outgoing
            daily_totals[day]['running_incoming'] = running_incoming
            daily_totals[day]['running_net'] = running_incoming - running_outgoing
        
        return daily_totals
    
    def on_calendar_date_selected(self):
        """Handle calendar date selection"""
        selected_date = self.calendar.selectedDate()
        day = selected_date.day()
        month = selected_date.month()
        year = selected_date.year()
        
        # Calculate daily totals
        daily_totals = self.calculate_daily_totals(month, year)
        
        # Format date
        date_str = selected_date.toString("dddd, MMMM d, yyyy")
        
        # Build details text
        details_html = f"<h2 style='color: #667eea;'>{date_str}</h2><br>"
        
        if day in daily_totals:
            totals = daily_totals[day]
            outgoing = totals.get('outgoing', 0)
            incoming = totals.get('incoming', 0)
            running_outgoing = totals.get('running_outgoing', 0)
            running_incoming = totals.get('running_incoming', 0)
            running_net = totals.get('running_net', 0)
            
            # Day-specific transactions
            details_html += "<h3 style='color: #ffffff; border-bottom: 2px solid #4a5568; padding-bottom: 5px;'>This Day's Transactions</h3>"
            
            if outgoing > 0:
                details_html += f"<h4 style='color: #ff6b6b;'>💸 Money Going Out: £{outgoing:,.2f}</h4>"
                details_html += "<ul>"
                for detail in totals['details']['outgoing']:
                    details_html += f"<li style='color: #ff8787;'>{detail}</li>"
                details_html += "</ul><br>"
            
            if incoming > 0:
                details_html += f"<h4 style='color: #51cf66;'>💰 Money Coming In: £{incoming:,.2f}</h4>"
                details_html += "<ul>"
                for detail in totals['details']['incoming']:
                    details_html += f"<li style='color: #69db7c;'>{detail}</li>"
                details_html += "</ul><br>"
            
            if outgoing == 0 and incoming == 0:
                details_html += "<p style='color: #a0a0a0;'>No transactions scheduled for this day.</p><br>"
            
            net = incoming - outgoing
            if net > 0:
                details_html += f"<h4 style='color: #51cf66;'>📊 Day's Net: +£{net:,.2f}</h4><br>"
            elif net < 0:
                details_html += f"<h4 style='color: #ff6b6b;'>📊 Day's Net: £{net:,.2f}</h4><br>"
            else:
                details_html += f"<h4 style='color: #ffffff;'>📊 Day's Net: £0.00</h4><br>"
            
            # Running totals from start of month
            details_html += "<h3 style='color: #ffffff; border-bottom: 2px solid #4a5568; padding-bottom: 5px; margin-top: 15px;'>Running Totals (Month to Date)</h3>"
            details_html += f"<h4 style='color: #ff6b6b;'>💸 Total Outgoing: £{running_outgoing:,.2f}</h4>"
            details_html += f"<h4 style='color: #51cf66;'>💰 Total Incoming: £{running_incoming:,.2f}</h4>"
            
            if running_net > 0:
                details_html += f"<h4 style='color: #51cf66;'>📊 Running Net: +£{running_net:,.2f}</h4>"
            elif running_net < 0:
                details_html += f"<h4 style='color: #ff6b6b;'>📊 Running Net: £{running_net:,.2f}</h4>"
            else:
                details_html += f"<h4 style='color: #ffffff;'>📊 Running Net: £0.00</h4>"
        else:
            details_html += "<p style='color: #a0a0a0;'>No payments or income scheduled for this day.</p>"
        
        self.day_details_text.setHtml(details_html)
    
    def on_calendar_month_changed(self, year, month):
        """Handle calendar month change"""
        self.refresh_calendar()
    
    def update_monthly_summary(self, month, year):
        """Update monthly summary with current totals"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        today = datetime.today().date()
        is_current_month = (month == today.month and year == today.year)
        
        # Calculate total payments from payment history (only what's been paid)
        cursor.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN payment_type IN ('recurring', 'one_time') THEN amount ELSE 0 END), 0) as total_payments
            FROM payment_history
            WHERE month = ? AND year = ?
        """, (month, year))
        
        result = cursor.fetchone()
        total_payments = result[0] if result[0] else 0
        
        # Calculate total income
        if is_current_month:
            # For current month: show all scheduled recurring income (not just received)
            cursor.execute("SELECT amount FROM recurring_income")
            recurring_income_list = cursor.fetchall()
            total_income = sum(income[0] for income in recurring_income_list) if recurring_income_list else 0
        else:
            # For past months: show only what was actually received
            cursor.execute("""
                SELECT COALESCE(SUM(amount), 0) FROM payment_history
                WHERE payment_type = 'income' AND month = ? AND year = ?
            """, (month, year))
            income_result = cursor.fetchone()
            total_income = income_result[0] if income_result and income_result[0] else 0
        
        # Get savings amount
        cursor.execute("""
            SELECT savings_amount FROM monthly_summary
            WHERE month = ? AND year = ?
        """, (month, year))
        savings_result = cursor.fetchone()
        savings = savings_result[0] if savings_result else 0
        
        net_savings = total_income - total_payments - savings
        
        # Update monthly summary
        cursor.execute("""
            INSERT OR REPLACE INTO monthly_summary 
            (month, year, total_payments, total_income, savings_amount, net_savings, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (month, year, total_payments, total_income, savings, net_savings))
        
        conn.commit()
        conn.close()
    
    def view_month_details(self, month, year):
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT payment_type, name, amount, payment_date
            FROM payment_history
            WHERE month = ? AND year = ?
            ORDER BY payment_date
        """, (month, year))
        
        transactions = cursor.fetchall()
        conn.close()
        
        details = f"<b>Details for {datetime(year, month, 1).strftime('%B %Y')}:</b><br><br>"
        
        if not transactions:
            details += "No transactions recorded."
        else:
            details += "<table border='1' cellpadding='5'>"
            details += "<tr><th>Type</th><th>Name</th><th>Amount</th><th>Date</th></tr>"
            for trans in transactions:
                trans_type, name, amount, date = trans
                date_obj = datetime.strptime(date, "%Y-%m-%d").date()
                details += f"<tr><td>{trans_type}</td><td>{name}</td><td>£{amount:,.2f}</td><td>{date_obj.strftime('%d/%m/%Y')}</td></tr>"
            details += "</table>"
        
        msg = QMessageBox(self)
        msg.setWindowTitle(f"Details - {datetime(year, month, 1).strftime('%B %Y')}")
        msg.setText(details)
        msg.exec()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FinanceApp()
    window.show()
    sys.exit(app.exec())

