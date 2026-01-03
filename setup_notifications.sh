#!/bin/bash

# Setup script for Finance App Daily Notifications

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PLIST_NAME="com.financeapp.notification.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_NAME"

echo "🔔 Finance App Notification Setup"
echo "=================================="
echo ""

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed or not in PATH"
    exit 1
fi

PYTHON_PATH=$(which python3)
echo "✓ Found Python 3 at: $PYTHON_PATH"

# Make notification script executable
chmod +x "$SCRIPT_DIR/notification_service.py"
echo "✓ Made notification_service.py executable"

# Test the notification script
echo ""
echo "Testing notification script..."
python3 "$SCRIPT_DIR/notification_service.py"
if [ $? -eq 0 ]; then
    echo "✓ Notification script test successful"
else
    echo "⚠️  Warning: Notification script had errors (check if database exists)"
fi

# Create LaunchAgents directory if it doesn't exist
mkdir -p "$LAUNCH_AGENTS_DIR"
echo "✓ LaunchAgents directory ready"

# Copy plist file
cp "$SCRIPT_DIR/$PLIST_NAME" "$PLIST_PATH"
echo "✓ Copied plist file to LaunchAgents"

# Update Python path in plist if needed
sed -i '' "s|/usr/bin/python3|$PYTHON_PATH|g" "$PLIST_PATH"
echo "✓ Updated Python path in plist file"

# Update script path in plist
sed -i '' "s|/Users/omareweis/Documents/Finance_app|$SCRIPT_DIR|g" "$PLIST_PATH"
echo "✓ Updated script path in plist file"

# Unload existing service if it exists
if launchctl list | grep -q "com.financeapp.notification"; then
    echo "Unloading existing service..."
    launchctl unload "$PLIST_PATH" 2>/dev/null
fi

# Load the service
echo ""
echo "Loading launch agent..."
launchctl load "$PLIST_PATH"

if [ $? -eq 0 ]; then
    echo "✓ Service loaded successfully!"
    echo ""
    echo "✅ Setup complete!"
    echo ""
    echo "The notification service will run daily at 9:00 AM"
    echo ""
    echo "To manage the service:"
    echo "  Start:   launchctl start com.financeapp.notification"
    echo "  Stop:    launchctl stop com.financeapp.notification"
    echo "  Unload:  launchctl unload $PLIST_PATH"
    echo ""
    echo "To test now, run:"
    echo "  launchctl start com.financeapp.notification"
    echo ""
else
    echo "❌ Error: Failed to load service"
    echo "Check the plist file syntax:"
    echo "  plutil -lint $PLIST_PATH"
    exit 1
fi

