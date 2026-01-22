#!/bin/bash
set -e

echo "================================================"
echo "Installing PJSIP with Python bindings (pjsua2)"
echo "================================================"

PJSIP_VERSION="2.14.1"
PJSIP_URL="https://github.com/pjsip/pjproject/archive/refs/tags/${PJSIP_VERSION}.tar.gz"
INSTALL_DIR="/tmp/pjproject-${PJSIP_VERSION}"

echo "→ Downloading PJSIP ${PJSIP_VERSION}..."
cd /tmp
wget -q ${PJSIP_URL} -O pjproject.tar.gz
tar -xzf pjproject.tar.gz
cd pjproject-${PJSIP_VERSION}

echo "→ Configuring PJSIP..."
./configure \
    --enable-shared \
    --disable-video \
    --disable-sound \
    --disable-sdl \
    --disable-ffmpeg \
    --disable-v4l2 \
    --disable-openh264 \
    --disable-libyuv \
    --disable-libwebrtc \
    CFLAGS="-O2 -fPIC" \
    CXXFLAGS="-O2 -fPIC"

echo "→ Building PJSIP (this may take several minutes)..."
make dep
make -j$(nproc)

echo "→ Installing PJSIP..."
make install
ldconfig

echo "→ Building Python bindings (pjsua2)..."
cd pjsip-apps/src/swig/python
make
python3 setup.py install

echo "→ Cleaning up..."
cd /
rm -rf /tmp/pjproject*

echo "→ Verifying installation..."
python3 -c "import pjsua2; print(f'✓ pjsua2 installed successfully: version {pjsua2.Endpoint.libVersion()}')" || echo "✗ pjsua2 installation failed"

echo "================================================"
echo "PJSIP installation completed!"
echo "================================================"
