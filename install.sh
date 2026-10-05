#!/usr/bin/env bash
# ==============================================================================
# portdock Installer Script
# Day 6: Interactive Port Conflict Resolver & Ghost Process Dissector
# ==============================================================================

set -e

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${CYAN}"
echo "=========================================================="
echo "  ⚡ Installing portdock - Ghost Process Dissector & TUI  "
echo "=========================================================="
echo -e "${NC}"

# 1. Check Python 3
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}Error: python3 is not installed or not in PATH.${NC}"
    echo "Please install Python 3.8+ (e.g. 'sudo apt install python3 python3-pip')"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "Found Python ${CYAN}${PYTHON_VERSION}${NC}"

# 2. Check Pip
if ! python3 -m pip --version &>/dev/null; then
    echo -e "${YELLOW}Warning: pip module not found. Attempting to install ensurepip...${NC}"
    python3 -m ensurepip --user || {
        echo -e "${RED}Failed to find or install pip. Please install python3-pip.${NC}"
        exit 1
    }
fi

# 3. Determine repository directory
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 4. Install dependencies & portdock
echo -e "Installing dependencies and portdock executable..."
python3 -m pip install --user --upgrade psutil rich hatchling
python3 -m pip install --user -e "$REPO_DIR"

# 5. Check ~/.local/bin in PATH
LOCAL_BIN="$HOME/.local/bin"
mkdir -p "$LOCAL_BIN"

if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    echo -e "${YELLOW}Notice: $LOCAL_BIN is not currently in your PATH.${NC}"
    echo -e "Add it to your shell configuration file (~/.bashrc, ~/.zshrc, or ~/.config/fish/config.fish):"
    echo -e "${CYAN}  export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
    export PATH="$LOCAL_BIN:$PATH"
fi

# 6. Verify portdock installation
if command -v portdock &>/dev/null; then
    echo -e "\n${GREEN}✓ portdock successfully installed! (${CYAN}$(portdock --version)${GREEN})${NC}\n"
else
    echo -e "\n${YELLOW}Installed to $LOCAL_BIN/portdock${NC}\n"
fi

echo -e "${CYAN}Quick Usage Examples:${NC}"
echo -e "  ${GREEN}portdock${NC}                  -> Launch full interactive TUI dashboard"
echo -e "  ${GREEN}portdock 3000${NC}             -> Dissect and inspect port 3000"
echo -e "  ${GREEN}portdock kill 3000${NC}        -> Terminate process holding port 3000"
echo -e "  ${GREEN}portdock kill 3000 -t${NC}     -> Purge supervisor and entire worker tree"
echo -e "  ${GREEN}portdock list --public${NC}    -> List only public sockets (0.0.0.0)"
echo -e "  ${GREEN}portdock wait 5432${NC}        -> Wait until port 5432 is freed\n"
