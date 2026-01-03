# Setting Up Daily Finance Notifications

This guide will help you set up daily notifications for your finance app on macOS.

## What It Does

The notification service will:
- Check for upcoming payments in the next 7 days
- Show you how much money you have left (net savings)
- Display remaining payments to be made
- Run automatically once per day at 9:00 AM

## Setup Instructions

### Step 1: Make the notification script executable

Open Terminal and run:

```bash
cd /Users/omareweis/Documents/Finance_app
chmod +x notification_service.py
```

### Step 2: Test the notification script

Test that it works by running it manually:

```bash
python3 notification_service.py
```

You should see two notifications:
1. Upcoming payments (if any are due in the next 7 days)
2. Financial summary for the current month

### Step 3: Update the plist file path (if needed)

If your Python 3 is in a different location, you may need to update the plist file:

1. Find your Python 3 path:
   ```bash
   which python3
   ```

2. Edit `com.financeapp.notification.plist` and replace `/usr/bin/python3` with your Python path if different.

3. Also verify the script path is correct: `/Users/omareweis/Documents/Finance_app/notification_service.py`

### Step 4: Load the launch agent

Load the launch agent to start the daily notifications:

```bash
cd /Users/omareweis/Documents/Finance_app
launchctl load ~/Library/LaunchAgents/com.financeapp.notification.plist
```

First, copy the plist file to the LaunchAgents directory:

```bash
cp com.financeapp.notification.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.financeapp.notification.plist
```

### Step 5: Verify it's loaded

Check that the service is loaded:

```bash
launchctl list | grep financeapp
```

You should see `com.financeapp.notification` in the list.

## Managing the Service

### Start the service manually (for testing)

```bash
launchctl start com.financeapp.notification
```

### Stop the service

```bash
launchctl stop com.financeapp.notification
```

### Unload the service (to disable daily notifications)

```bash
launchctl unload ~/Library/LaunchAgents/com.financeapp.notification.plist
```

### Change the notification time

Edit the plist file and change the `Hour` and `Minute` values:

```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>9</integer>  <!-- Change this (0-23) -->
    <key>Minute</key>
    <integer>0</integer>   <!-- Change this (0-59) -->
</dict>
```

Then reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.financeapp.notification.plist
launchctl load ~/Library/LaunchAgents/com.financeapp.notification.plist
```

## Troubleshooting

### Notifications not appearing

1. Check macOS notification settings:
   - System Settings → Notifications & Focus
   - Make sure Terminal (or Python) has notification permissions

2. Check the log files:
   ```bash
   cat /Users/omareweis/Documents/Finance_app/notification.log
   cat /Users/omareweis/Documents/Finance_app/notification_error.log
   ```

3. Test manually:
   ```bash
   python3 notification_service.py
   ```

### Service not running

1. Check if it's loaded:
   ```bash
   launchctl list | grep financeapp
   ```

2. Check the plist file syntax:
   ```bash
   plutil -lint ~/Library/LaunchAgents/com.financeapp.notification.plist
   ```

3. Try loading again:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.financeapp.notification.plist
   launchctl load ~/Library/LaunchAgents/com.financeapp.notification.plist
   ```

### Database not found

Make sure `finance.db` is in the same directory as `notification_service.py`:
```bash
ls -la /Users/omareweis/Documents/Finance_app/finance.db
```

## Customization

You can modify `notification_service.py` to:
- Change the number of days to check ahead (currently 7 days)
- Customize the notification messages
- Add more financial metrics
- Change notification frequency (though the plist controls the schedule)

## Notes

- The service runs once per day at the scheduled time
- It requires your laptop to be on and logged in
- Notifications use macOS's native notification system
- The service will automatically retry if it fails

