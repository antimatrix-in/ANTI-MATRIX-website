#!/usr/bin/env bash
# Render Build Script for Anti-Matrix
# Installs Python dependencies and ensures LibreOffice headless is available for DOCX->PDF preview
set -o errexit

echo "=================================================="
echo " Anti-Matrix Build Process Starting"
echo "=================================================="

# 1. Install Python packages
echo "==> Upgrading pip and installing Python dependencies..."
python -m pip install --upgrade pip
pip install -r requirements.txt

# 2. Check and Install LibreOffice Headless for PDF Preview
echo "==> Checking for LibreOffice installation..."
if command -v libreoffice &> /dev/null || command -v soffice &> /dev/null; then
    echo "==> LibreOffice already installed:"
    libreoffice --version 2>/dev/null || soffice --version 2>/dev/null || true
else
    echo "==> LibreOffice not found in PATH. Checking package manager..."
    if command -v apt-get &> /dev/null; then
        echo "==> Installing libreoffice-writer-nogui and fonts via apt-get..."
        apt-get update -qq
        apt-get install -y --no-install-recommends \
            libreoffice-writer-nogui \
            default-jre-headless \
            fonts-dejavu \
            fonts-liberation \
            fontconfig
        echo "==> LibreOffice headless installed successfully!"
        libreoffice --version || true
    else
        echo "==> WARNING: apt-get not available in current environment."
        echo "==> Render Native Python runtime cannot install system packages like LibreOffice."
        echo "==> Set Web Service runtime to 'Docker' in Render Dashboard Settings to use Dockerfile."
    fi
fi

echo "=================================================="
echo " Anti-Matrix Build Process Completed Successfully"
echo "=================================================="
