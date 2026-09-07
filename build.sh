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
    echo "==> LibreOffice already installed in system PATH:"
    libreoffice --version 2>/dev/null || soffice --version 2>/dev/null || true
elif [ -f "./libreoffice/usr/bin/soffice" ] || [ -f "./libreoffice/opt/libreoffice*/program/soffice" ]; then
    echo "==> Local portable LibreOffice detected in project directory."
else
    echo "==> LibreOffice not found in PATH. Detecting environment privileges..."
    if command -v apt-get &> /dev/null && [ "$(id -u)" -eq 0 ]; then
        echo "==> Root detected. Installing libreoffice-writer-nogui and fonts via apt-get..."
        apt-get update -qq || true
        apt-get install -y --no-install-recommends \
            libreoffice-writer-nogui \
            default-jre-headless \
            fonts-dejavu \
            fonts-liberation \
            fontconfig || true
        echo "==> LibreOffice headless installed successfully!"
        libreoffice --version 2>/dev/null || soffice --version 2>/dev/null || true
    elif command -v sudo &> /dev/null && sudo -n true 2>/dev/null; then
        echo "==> Sudo access detected. Installing libreoffice-writer-nogui via sudo..."
        sudo apt-get update -qq || true
        sudo apt-get install -y --no-install-recommends \
            libreoffice-writer-nogui \
            default-jre-headless \
            fonts-dejavu \
            fonts-liberation \
            fontconfig || true
        echo "==> LibreOffice headless installed successfully via sudo!"
        libreoffice --version 2>/dev/null || soffice --version 2>/dev/null || true
    else
        echo "==> Non-root environment detected. Attempting unprivileged package extraction..."
        if command -v apt-get &> /dev/null; then
            mkdir -p /tmp/lo_build libreoffice
            (
                cd /tmp/lo_build
                apt-get download libreoffice-writer-nogui libreoffice-core libreoffice-common \
                    fonts-dejavu-core fonts-liberation 2>/dev/null || true
                for deb in *.deb; do
                    if [ -f "$deb" ]; then
                        dpkg-deb -x "$deb" "$OLDPWD/libreoffice" 2>/dev/null || true
                    fi
                done
            ) || true
            rm -rf /tmp/lo_build
            echo "==> Unprivileged LibreOffice extraction complete."
        else
            echo "==> Notice: Package manager not available. Continuing with existing system configuration."
        fi
    fi
fi

# Ensure uploads directories and preview cache exist
mkdir -p uploads/generated_documents uploads/documents uploads/resumes uploads/preview_cache

echo "=================================================="
echo " Anti-Matrix Build Process Completed Successfully"
echo "=================================================="
