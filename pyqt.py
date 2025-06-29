# payment_tracker.py
import sys
import os
import pandas as pd
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTableWidget, QTableWidgetItem, QMessageBox, QDateEdit, QFileDialog, QLabel, QGroupBox, QGridLayout, QTabWidget, QComboBox
)
from PyQt6.QtCore import Qt, QDate
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import matplotlib.pyplot as plt

COLUMNS = ["Scheduled Payment", "Price", "Previous Date", "Date", "Next Date", "Paid", "Outstanding"]
SAVE_FILE = "payments.csv"

class PaymentTracker(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Payment Tracker")
        self.resize(1100, 800)
        
        # Set matplotlib to use dark background globally
        plt.style.use('dark_background')
        
        # Set dark theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QGroupBox {
                background-color: #3c3c3c;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
                color: #ffffff;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
                color: #ffffff;
            }
            QTableWidget {
                background-color: #3c3c3c;
                color: #ffffff;
                gridline-color: #555555;
            }
            QTableWidget::item {
                background-color: #3c3c3c;
                color: #ffffff;
            }
            QTableWidget::item:selected {
                background-color: #4a4a4a;
            }
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #2b2b2b;
            }
            QTabBar::tab {
                background-color: #3c3c3c;
                color: #ffffff;
                padding: 8px 16px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background-color: #4a4a4a;
            }
            QPushButton {
                background-color: #4a4a4a;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 5px 10px;
                border-radius: 3px;
            }
            QPushButton:hover {
                background-color: #5a5a5a;
            }
            QComboBox {
                background-color: #3c3c3c;
                color: #ffffff;
                border: 1px solid #555555;
                padding: 2px;
            }
        """)

        self.data = pd.DataFrame(columns=COLUMNS)
        self.load_data()

        # --- Summary Metrics ---
        self.total_label = QLabel()
        self.outstanding_label = QLabel()
        self.update_summary_labels()

        summary_box = QGroupBox("Summary")
        summary_layout = QHBoxLayout()
        summary_layout.addWidget(self.total_label)
        summary_layout.addWidget(self.outstanding_label)
        summary_box.setLayout(summary_layout)

        # --- Pie Chart ---
        self.pie_canvas = FigureCanvas(plt.Figure(figsize=(5, 5)))
        self.update_pie_chart()

        # --- Monthly Chart ---
        self.monthly_canvas = FigureCanvas(plt.Figure(figsize=(6, 4)))
        self.update_monthly_chart()

        # --- Table and Buttons ---
        self.table = QTableWidget()
        self.setup_table()

        # Check for overdue payments AFTER table is created
        if self.check_and_update_overdue_payments():
            QMessageBox.information(self, "Payments Updated", "Overdue payments have been automatically updated on startup.")

        self.add_button = QPushButton("➕ Add Row")
        self.add_button.clicked.connect(self.add_row)

        self.remove_button = QPushButton("🗑️ Remove Row")
        self.remove_button.clicked.connect(self.remove_row)

        self.update_button = QPushButton("🔄 Auto Update Payments")
        self.update_button.clicked.connect(self.auto_update)

        self.save_button = QPushButton("💾 Save")
        self.save_button.clicked.connect(self.save_data)

        self.upload_button = QPushButton("⬆️ Upload CSV")
        self.upload_button.clicked.connect(self.upload_csv)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.update_button)
        button_layout.addWidget(self.save_button)
        button_layout.addWidget(self.upload_button)

        # --- Dashboard Tab ---
        dashboard_widget = QWidget()
        dashboard_layout = QVBoxLayout()
        dashboard_layout.addWidget(summary_box)
        dashboard_layout.addWidget(self.pie_canvas)
        dashboard_layout.addWidget(self.monthly_canvas)
        dashboard_widget.setLayout(dashboard_layout)

        # --- Data Tab ---
        data_widget = QWidget()
        data_layout = QVBoxLayout()
        data_layout.addLayout(button_layout)
        data_layout.addWidget(self.table)
        data_widget.setLayout(data_layout)

        # --- Tabs ---
        self.tabs = QTabWidget()
        self.tabs.addTab(dashboard_widget, "Dashboard")
        self.tabs.addTab(data_widget, "Raw Data")

        # --- Main Layout ---
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tabs)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.table.cellDoubleClicked.connect(self.handle_cell_double_clicked)

    def load_data(self):
        if os.path.exists(SAVE_FILE):
            self.data = pd.read_csv(SAVE_FILE)
            # Remove the "Running Total" column if it exists in the CSV
            if "Running Total" in self.data.columns:
                self.data = self.data.drop(columns=["Running Total"])
        else:
            self.data = pd.DataFrame(columns=COLUMNS)

    def save_data(self):
        self.data.to_csv(SAVE_FILE, index=False)
        self.update_summary_labels()
        self.update_pie_chart()
        self.update_monthly_chart()

    def setup_table(self):
        self.table.blockSignals(True)
        self.table.setColumnCount(len(COLUMNS) + 1)  # +1 for row numbers
        self.table.setHorizontalHeaderLabels(["#"] + COLUMNS)  # Add "#" header
        self.table.setRowCount(len(self.data))

        for row_idx, row in self.data.iterrows():
            # Add row number in first column
            row_number_item = QTableWidgetItem(str(row_idx + 1))
            row_number_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            row_number_item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # Make it read-only
            self.table.setItem(row_idx, 0, row_number_item)
            
            for col_idx, value in enumerate(row):
                col_name = COLUMNS[col_idx]
                if col_name == "Paid":
                    combo = QComboBox()
                    combo.addItems(["🟢 Yes", "🔴 No"])
                    # Set current value
                    if str(value).strip() == "🟢 Yes":
                        combo.setCurrentIndex(0)
                    else:
                        combo.setCurrentIndex(1)
                    # Connect change event
                    combo.currentIndexChanged.connect(
                        lambda idx, r=row_idx, c=col_idx+1: self.handle_paid_changed(r, c)  # +1 for row number column
                    )
                    self.table.setCellWidget(row_idx, col_idx + 1, combo)  # +1 for row number column
                elif col_name == "Price":
                    # Format price with pound symbol
                    try:
                        # Remove existing pound symbols and convert to float
                        clean_value = str(value).replace('£', '').replace(',', '').strip()
                        if clean_value and clean_value != 'nan':
                            float_value = float(clean_value)
                            formatted_price = f"£{float_value:,.2f}"
                        else:
                            formatted_price = "£0.00"
                    except (ValueError, TypeError):
                        formatted_price = "£0.00"
                    
                    item = QTableWidgetItem(formatted_price)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row_idx, col_idx + 1, item)  # +1 for row number column
                else:
                    item = QTableWidgetItem(str(value))
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.table.setItem(row_idx, col_idx + 1, item)  # +1 for row number column

        self.table.cellChanged.connect(self.update_dataframe)
        self.table.blockSignals(False)
        self.update_summary_labels()
        self.update_pie_chart()
        self.update_monthly_chart()

    def update_dataframe(self, row, col):
        if col > 0:  # Skip row number column
            value = self.table.item(row, col).text()
            col_name = COLUMNS[col - 1]  # -1 because we added row number column
            
            # Handle price formatting
            if col_name == "Price":
                # Remove pound symbol and commas for storage
                clean_value = value.replace('£', '').replace(',', '').strip()
                try:
                    float(clean_value)  # Validate it's a number
                    value = clean_value  # Store without formatting
                except ValueError:
                    value = "0"  # Default to 0 if invalid
            
            if row >= len(self.data):
                self.data.loc[row] = [""] * len(COLUMNS)
            self.data.iat[row, col - 1] = value  # -1 because we added row number column
            self.save_data()

    def add_row(self):
        row_index = self.table.rowCount()
        self.table.insertRow(row_index)
        self.data.loc[row_index] = [""] * len(COLUMNS)
        self.save_data()

    def auto_update(self):
        """Auto update payments - now uses the new check function"""
        if self.check_and_update_overdue_payments():
            QMessageBox.information(self, "Payments Updated", "Marked due items as paid and updated dates.")
        else:
            QMessageBox.information(self, "No Changes", "No payments were due today.")

    def handle_cell_double_clicked(self, row, col):
        if col > 0:  # Skip row number column
            col_name = COLUMNS[col - 1]  # -1 because we added row number column
            if col_name in ["Previous Date", "Date", "Next Date"]:
                current_value = self.table.item(row, col).text()
                try:
                    date = datetime.strptime(current_value, "%d/%m/%Y")
                    qdate = QDate(date.year, date.month, date.day)
                except Exception:
                    qdate = QDate.currentDate()

                date_edit = QDateEdit()
                date_edit.setCalendarPopup(True)
                date_edit.setDate(qdate)
                self.table.setCellWidget(row, col, date_edit)

                def on_date_changed(qdate):
                    new_date = qdate.toString("dd/MM/yyyy")
                    self.table.setItem(row, col, QTableWidgetItem(new_date))
                    self.table.setCellWidget(row, col, None)
                    self.update_dataframe(row, col)

                date_edit.dateChanged.connect(on_date_changed)
                date_edit.setFocus()

    def upload_csv(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            "Open Data File",
            "",
            "Data Files (*.csv *.xlsx);;CSV Files (*.csv);;Excel Files (*.xlsx)"
        )
        if file_name:
            try:
                if file_name.lower().endswith('.csv'):
                    df = pd.read_csv(file_name)
                elif file_name.lower().endswith('.xlsx'):
                    df = pd.read_excel(file_name)
                else:
                    QMessageBox.critical(self, "Error", "Unsupported file type selected.")
                    return

                # Drop "Running Total" if present
                if "Running Total" in df.columns:
                    df = df.drop(columns=["Running Total"])
                
                # Add "Previous Date" column if it doesn't exist
                if "Previous Date" not in df.columns:
                    df["Previous Date"] = ""
                
                # Only keep columns that match COLUMNS
                df = df[[col for col in COLUMNS if col in df.columns]]
                # Fill missing columns with empty strings
                for col in COLUMNS:
                    if col not in df.columns:
                        df[col] = ""
                df = df[COLUMNS]  # Ensure correct order

                # Format date columns to dd/MM/yyyy and remove any time
                for date_col in ["Previous Date", "Date", "Next Date"]:
                    if date_col in df.columns:
                        df[date_col] = pd.to_datetime(df[date_col], errors='coerce').dt.strftime('%d/%m/%Y').fillna(df[date_col])

                # Calculate Previous Date for rows where it's empty but Date exists
                for idx, row in df.iterrows():
                    if (pd.isna(row["Previous Date"]) or row["Previous Date"] == "" or row["Previous Date"] == "NaT") and row["Date"] != "":
                        try:
                            current_date = datetime.strptime(str(row["Date"]), "%d/%m/%Y").date()
                            previous_date = current_date - timedelta(days=30)  # 1 month before
                            df.at[idx, "Previous Date"] = previous_date.strftime("%d/%m/%Y")
                        except Exception as e:
                            print(f"Error calculating previous date for row {idx}: {e}")

                self.data = df
                self.setup_table()
                
                # Check for overdue payments after uploading
                if self.check_and_update_overdue_payments():
                    QMessageBox.information(self, "File Uploaded", "File loaded successfully and overdue payments have been updated.")
                else:
                    QMessageBox.information(self, "File Uploaded", "File loaded successfully.")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load file: {e}")

    def update_summary_labels(self):
        try:
            total = self.data["Price"].replace('[£, ]', '', regex=True).astype(float).sum()
            outstanding = self.data["Outstanding"].replace('[£, ]', '', regex=True).replace('', 0).astype(float).sum()
        except Exception:
            total = 0
            outstanding = 0
        self.total_label.setText(f"<b>Total Scheduled:</b> £{total:,.2f}")
        self.outstanding_label.setText(f"<b>Total Outstanding:</b> £{outstanding:,.2f}")

    def update_pie_chart(self):
        # Set matplotlib to use dark background
        plt.style.use('dark_background')
        
        ax = self.pie_canvas.figure.subplots()
        ax.clear()
        
        # Set the figure background to match your app
        self.pie_canvas.figure.patch.set_facecolor('#2b2b2b')
        ax.set_facecolor('#2b2b2b')
        
        try:
            outstanding = self.data["Outstanding"].replace('[£, ]', '', regex=True).replace('', 0).astype(float).sum()
            paid = self.data["Price"].replace('[£, ]', '', regex=True).astype(float).sum() - outstanding
            
            # Modern colors
            colors = ['#4CAF50', '#FF5722']
            
            # Create donut chart
            wedges, texts, autotexts = ax.pie(
                [paid, outstanding], 
                labels=["Paid", "Outstanding"], 
                autopct='%1.1f%%', 
                colors=colors,
                startangle=90,
                textprops={'fontsize': 10, 'fontweight': 'bold', 'color': 'white'},
                wedgeprops={'edgecolor': '#2b2b2b', 'linewidth': 2}
            )
            
            # Create a circle in the center to make it a donut
            centre_circle = plt.Circle((0,0), 0.6, fc='#2b2b2b')
            ax.add_artist(centre_circle)
            
            # Style the percentage text
            for autotext in autotexts:
                autotext.set_color('white')
                autotext.set_fontweight('bold')
            
            # Add title with white text
            ax.set_title("Payment Status", fontsize=14, fontweight='bold', pad=20, color='white')
            
            # Add center text with white color
            total = paid + outstanding
            ax.text(0, 0, f'£{total:,.0f}\nTotal', ha='center', va='center', 
                   fontsize=12, fontweight='bold', color='white')
            
        except Exception:
            ax.text(0.5, 0.5, "No data", ha='center', fontsize=12, color='white')
        
        self.pie_canvas.figure.tight_layout()
        self.pie_canvas.draw()

    def update_monthly_chart(self):
        # Set matplotlib to use dark background
        plt.style.use('dark_background')
        
        ax = self.monthly_canvas.figure.subplots()
        ax.clear()
        
        # Set the figure background to match your app
        self.monthly_canvas.figure.patch.set_facecolor('#2b2b2b')
        ax.set_facecolor('#2b2b2b')
        
        try:
            if not self.data.empty:
                # Convert "Date" to datetime, drop rows where conversion fails
                df = self.data.copy()
                df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y", errors='coerce')
                df = df.dropna(subset=["Date"])
                df["Price"] = df["Price"].replace('[£, ]', '', regex=True).replace('', 0).astype(float)

                today = datetime.today().date()

                # Group by year and month, sum the prices
                monthly = df.groupby(df["Date"].dt.to_period("M"))["Price"].sum()
                monthly = monthly.sort_index()

                months = []
                values = []
                for period, value in monthly.items():
                    period_date = period.to_timestamp().date()
                    # Include all months (past and current)
                    months.append(period_date)
                    values.append(value)

                # Plot as line graph
                if months:
                    ax.plot(months, values, marker='o', linewidth=2, markersize=6, color='#4CAF50')
                    ax.set_xticks(months)
                    ax.set_xticklabels([d.strftime("%b %Y") for d in months], rotation=45, color='white')
                ax.set_title("Total Monthly Payments", fontsize=14, fontweight='bold', color='white')
                ax.set_xlabel("Month", color='white')
                ax.set_ylabel("Total (£)", color='white')
                
                # Set grid and tick colors
                ax.grid(True, alpha=0.3, color='#555555')
                ax.tick_params(colors='white')
                
                self.monthly_canvas.figure.tight_layout()
            else:
                ax.text(0.5, 0.5, "No data", ha='center', color='white')
        except Exception as e:
            ax.text(0.5, 0.5, f"No data\n{e}", ha='center', color='white')
        
        self.monthly_canvas.draw()

    def handle_paid_changed(self, row, col):
        combo = self.table.cellWidget(row, col)
        if combo:
            value = combo.currentText()
            old_value = self.data.iat[row, col - 1]  # -1 because we added row number column
            self.data.iat[row, col - 1] = value
            
            # If status changed from "🔴 No" to "🟢 Yes", update dates
            if old_value == "🔴 No" and value == "🟢 Yes":
                try:
                    # Get current dates
                    current_date = datetime.strptime(str(self.data.at[row, "Date"]), "%d/%m/%Y").date()
                    next_date = datetime.strptime(str(self.data.at[row, "Next Date"]), "%d/%m/%Y").date()
                    
                    # Shift dates
                    self.data.at[row, "Previous Date"] = current_date.strftime("%d/%m/%Y")
                    self.data.at[row, "Date"] = next_date.strftime("%d/%m/%Y")
                    self.data.at[row, "Next Date"] = (next_date + timedelta(days=30)).strftime("%d/%m/%Y")
                    self.data.at[row, "Outstanding"] = 0
                    
                    # Refresh the table to show updated dates
                    self.setup_table()
                except Exception as e:
                    print(f"Error updating dates for row {row}: {e}")
            
            self.save_data()

    def check_and_update_overdue_payments(self):
        """Check for overdue payments and update them automatically, catching up multiple cycles if needed."""
        today = datetime.today().date()
        updated = False

        for i, row in self.data.iterrows():
            try:
                # Only process if there is a valid date
                if row["Date"] != "" and row["Date"] != "NaT":
                    current_date = datetime.strptime(str(row["Date"]), "%d/%m/%Y").date()
                    next_date = None
                    if row["Next Date"] != "" and row["Next Date"] != "NaT":
                        next_date = datetime.strptime(str(row["Next Date"]), "%d/%m/%Y").date()
                    else:
                        next_date = current_date + timedelta(days=30)

                    # If the payment is overdue, keep shifting until the date is in the future
                    while current_date <= today:
                        # Mark as paid for the overdue period
                        self.data.at[i, "Paid"] = "🟢 Yes"
                        self.data.at[i, "Outstanding"] = 0
                        self.data.at[i, "Previous Date"] = current_date.strftime("%d/%m/%Y")
                        self.data.at[i, "Date"] = next_date.strftime("%d/%m/%Y")
                        self.data.at[i, "Next Date"] = (next_date + timedelta(days=30)).strftime("%d/%m/%Y")
                        updated = True

                        # Prepare for next cycle
                        current_date = next_date
                        next_date = current_date + timedelta(days=30)

                    # Reset to "🔴 No" at the end of the month
                    last_day_of_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
                    if (self.data.at[i, "Paid"] == "🟢 Yes" and 
                        today == last_day_of_month):
                        self.data.at[i, "Paid"] = "🔴 No"
                        
            except Exception as e:
                print(f"Error checking overdue payment in row {i}: {e}")

        if updated:
            self.setup_table()
            self.save_data()
            return True
        return False

    def remove_row(self):
        current_row = self.table.currentRow()
        if current_row >= 0:
            reply = QMessageBox.question(
                self, 
                "Remove Row", 
                f"Are you sure you want to remove row {current_row + 1}?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.table.removeRow(current_row)
                self.data = self.data.drop(current_row).reset_index(drop=True)
                self.save_data()
        else:
            QMessageBox.warning(self, "No Selection", "Please select a row to remove.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PaymentTracker()
    window.show()
    sys.exit(app.exec())
