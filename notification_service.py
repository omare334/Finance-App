#!/usr/bin/env python3
"""
Daily Finance Notification Service
Checks for upcoming payments and sends notifications about financial status
"""
import sys
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

# Add the app directory to the path
DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "finance.db")

def send_notification(title, message, subtitle=""):
    """Send a macOS notification using osascript"""
    script = f'''
    display notification "{message}" with title "{title}" subtitle "{subtitle}"
    '''
    os.system(f"osascript -e '{script}'")

def get_connection():
    """Get database connection"""
    conn = sqlite3.connect(DB_FILE, timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def calculate_payment_dates(payment_day, last_paid_date, current_month, current_year):
    """Calculate payment dates for a recurring payment"""
    today = datetime.today().date()
    
    # Calculate this month's payment date
    try:
        this_month_date = datetime(current_year, current_month, min(payment_day, 28)).date()
        # Adjust if day doesn't exist in month (e.g., Feb 30 -> Feb 28)
        while this_month_date.month != current_month:
            this_month_date -= timedelta(days=1)
    except ValueError:
        # If day is invalid, use last day of month
        if current_month == 12:
            this_month_date = datetime(current_year, 12, 31).date()
        else:
            this_month_date = datetime(current_year, current_month + 1, 1).date() - timedelta(days=1)
    
    # Calculate next month's payment date
    if current_month == 12:
        next_month_date = datetime(current_year + 1, 1, min(payment_day, 28)).date()
    else:
        next_month_date = datetime(current_year, current_month + 1, min(payment_day, 28)).date()
    
    # Adjust if day doesn't exist
    while next_month_date.month != (current_month % 12 + 1 if current_month < 12 else 1):
        next_month_date -= timedelta(days=1)
    
    # Calculate last month's payment date
    if current_month == 1:
        last_month_date = datetime(current_year - 1, 12, min(payment_day, 28)).date()
    else:
        last_month_date = datetime(current_year, current_month - 1, min(payment_day, 28)).date()
    
    while last_month_date.month != (current_month - 1 if current_month > 1 else 12):
        last_month_date -= timedelta(days=1)
    
    # Determine which date to use based on last_paid_date
    if last_paid_date:
        # Try to parse the date
        try:
            if isinstance(last_paid_date, str):
                # Try datetime format first
                try:
                    last_paid = datetime.strptime(last_paid_date, "%Y-%m-%d %H:%M:%S").date()
                except ValueError:
                    # Try date-only format
                    try:
                        last_paid = datetime.strptime(last_paid_date, "%Y-%m-%d").date()
                    except ValueError:
                        # Fallback: extract date part
                        last_paid = datetime.strptime(str(last_paid_date).split()[0], "%Y-%m-%d").date()
            else:
                last_paid = last_paid_date
        except:
            last_paid = None
    else:
        last_paid = None
    
    # If last paid date is after this month's date, use next month's date
    if last_paid and this_month_date <= last_paid:
        current_date = next_month_date
    else:
        current_date = this_month_date
    
    return last_month_date, current_date, next_month_date

def check_upcoming_payments():
    """Check for upcoming payments in the next 7 days"""
    today = datetime.today().date()
    conn = get_connection()
    cursor = conn.cursor()
    
    upcoming_payments = []
    
    # Check recurring payments
    cursor.execute("""
        SELECT id, name, amount, payment_day, 
               COALESCE(payment_type, 'debit') as payment_type,
               last_paid_date 
        FROM recurring_payments
    """)
    recurring_payments = cursor.fetchall()
    
    current_month = today.month
    current_year = today.year
    
    for payment in recurring_payments:
        payment_id, name, amount, payment_day, payment_type, last_paid_date = payment
        _, current_date, next_date = calculate_payment_dates(
            payment_day, last_paid_date, current_month, current_year
        )
        
        # Check if payment is due in the next 7 days
        days_until = (current_date - today).days
        if 0 <= days_until <= 7:
            # Check if already paid this month
            cursor.execute("""
                SELECT COUNT(*) FROM payment_history
                WHERE payment_id = ? AND payment_type = 'recurring'
                AND month = ? AND year = ?
            """, (payment_id, current_month, current_year))
            is_paid = cursor.fetchone()[0] > 0
            
            if not is_paid:
                upcoming_payments.append({
                    'name': name,
                    'amount': amount,
                    'date': current_date,
                    'days_until': days_until,
                    'type': payment_type
                })
    
    # Check one-time payments
    cursor.execute("""
        SELECT name, amount, payment_date FROM one_time_payments
        WHERE paid = 0
    """)
    one_time_payments = cursor.fetchall()
    
    for payment in one_time_payments:
        name, amount, payment_date_str = payment
        try:
            if isinstance(payment_date_str, str):
                try:
                    payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d %H:%M:%S").date()
                except ValueError:
                    payment_date = datetime.strptime(payment_date_str, "%Y-%m-%d").date()
            else:
                payment_date = payment_date_str
            
            days_until = (payment_date - today).days
            if 0 <= days_until <= 7:
                upcoming_payments.append({
                    'name': name,
                    'amount': amount,
                    'date': payment_date,
                    'days_until': days_until,
                    'type': 'debit'
                })
        except:
            continue
    
    conn.close()
    return upcoming_payments

def get_financial_summary():
    """Get current month's financial summary"""
    today = datetime.today().date()
    current_month = today.month
    current_year = today.year
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Total income (scheduled)
    cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM recurring_income")
    total_income = cursor.fetchone()[0] or 0
    
    # Total scheduled payments
    cursor.execute("SELECT amount, COALESCE(payment_type, 'debit') as payment_type FROM recurring_payments")
    recurring_payments = cursor.fetchall()
    total_scheduled = 0
    total_credit = 0
    total_debit = 0
    
    for payment in recurring_payments:
        amount = payment[0]
        payment_type = payment[1] if len(payment) > 1 else 'debit'
        total_scheduled += amount
        if payment_type and payment_type.lower() == 'credit':
            total_credit += amount
        else:
            total_debit += amount
    
    # One-time payments for this month
    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) FROM one_time_payments
        WHERE strftime('%m', payment_date) = ? AND strftime('%Y', payment_date) = ?
    """, (f"{current_month:02d}", str(current_year)))
    one_time_total = cursor.fetchone()[0] or 0
    total_debit += one_time_total
    total_scheduled += one_time_total
    
    # Already paid this month
    cursor.execute("""
        SELECT ph.amount, rp.payment_type
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
        payment_type = paid[1] if len(paid) > 1 and paid[1] else 'debit'
        already_paid += amount
        if payment_type and payment_type.lower() == 'credit':
            credit_paid += amount
        else:
            debit_paid += amount
    
    # Remaining to pay
    remaining_to_pay = total_scheduled - already_paid
    remaining_credit = total_credit - credit_paid
    remaining_debit = total_debit - debit_paid
    
    # Net savings
    net_savings = total_income - total_scheduled
    
    conn.close()
    
    return {
        'total_income': total_income,
        'total_scheduled': total_scheduled,
        'already_paid': already_paid,
        'remaining_to_pay': remaining_to_pay,
        'remaining_credit': remaining_credit,
        'remaining_debit': remaining_debit,
        'net_savings': net_savings
    }

def check_and_delete_pending_deletions():
    """Check if it's a new month and delete payments marked for deletion"""
    today = datetime.today().date()
    current_month = today.month
    current_year = today.year
    
    conn = get_connection()
    cursor = conn.cursor()
    
    # Ensure app_settings table exists (created by main app, but might not exist yet)
    try:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
    except:
        pass
    
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
    deleted_count = 0
    if is_new_month:
        cursor.execute("""
            SELECT id, name FROM recurring_payments 
            WHERE delete_next_month = 1
        """)
        pending_deletions = cursor.fetchall()
        
        if pending_deletions:
            deleted_names = []
            
            for payment_id, payment_name in pending_deletions:
                # Delete the payment
                cursor.execute("DELETE FROM recurring_payments WHERE id = ?", (payment_id,))
                deleted_count += 1
                deleted_names.append(payment_name)
            
            if deleted_count > 0:
                conn.commit()
                # Send notification about deletions
                names_list = "\n".join([f"• {name}" for name in deleted_names])
                send_notification(
                    title="🗑️ Payments Deleted",
                    subtitle=f"{deleted_count} payment(s) removed",
                    message=f"New month detected! Removed:\n{names_list}"
                )
    
    conn.commit()
    conn.close()
    return deleted_count

def check_and_disable_expired_payments():
    """Check for payments that have exceeded their pay period and disable them"""
    today = datetime.today().date()
    current_month = today.month
    current_year = today.year
    
    conn = get_connection()
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
        names_list = "\n".join([f"• {name}" for name in expired_names])
        send_notification(
            title="⏰ Payments Expired",
            subtitle=f"{expired_count} payment(s) disabled",
            message=f"Pay period ended:\n{names_list}"
        )
    
    conn.commit()
    conn.close()
    return expired_count

def main():
    """Main notification function"""
    try:
        # Check and delete payments marked for deletion (if new month)
        check_and_delete_pending_deletions()
        
        # Check and disable expired payments
        check_and_disable_expired_payments()
        
        # Check upcoming payments
        upcoming = check_upcoming_payments()
        
        # Get financial summary
        summary = get_financial_summary()
        
        # Build notification message
        messages = []
        
        if upcoming:
            payment_list = []
            for payment in sorted(upcoming, key=lambda x: x['days_until']):
                days_text = "today" if payment['days_until'] == 0 else f"in {payment['days_until']} days"
                payment_list.append(f"• {payment['name']}: £{payment['amount']:.2f} ({days_text})")
            
            payment_msg = "\n".join(payment_list[:5])  # Limit to 5 payments
            if len(upcoming) > 5:
                payment_msg += f"\n... and {len(upcoming) - 5} more"
            
            send_notification(
                title="💰 Upcoming Payments",
                subtitle=f"{len(upcoming)} payment(s) due soon",
                message=payment_msg
            )
        
        # Financial summary notification
        net_savings = summary['net_savings']
        remaining = summary['remaining_to_pay']
        
        if net_savings >= 0:
            savings_msg = f"Net Savings: £{net_savings:,.2f}"
        else:
            savings_msg = f"Net Deficit: £{abs(net_savings):,.2f}"
        
        summary_msg = f"{savings_msg}\nRemaining to pay: £{remaining:,.2f}"
        
        if summary['remaining_credit'] > 0:
            summary_msg += f"\nRemaining credit: £{summary['remaining_credit']:,.2f}"
        
        send_notification(
            title="📊 Financial Summary",
            subtitle=f"Month: {datetime.today().strftime('%B %Y')}",
            message=summary_msg
        )
        
    except Exception as e:
        send_notification(
            title="❌ Finance App Error",
            message=f"Error checking finances: {str(e)}"
        )
        sys.exit(1)

if __name__ == "__main__":
    main()

