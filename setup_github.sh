#!/bin/bash
#
# Setup script for GitHub Pages deployment
# Run this after creating your GitHub repository
#

set -e

echo "=========================================="
echo "GitHub Pages Setup for AI Finance Tech"
echo "=========================================="
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if we're in the right directory
if [ ! -f "README.md" ]; then
    echo -e "${RED}Error: Please run this script from the workspace root directory${NC}"
    exit 1
fi

# Get GitHub username
echo -n "Enter your GitHub username: "
read USERNAME

if [ -z "$USERNAME" ]; then
    echo -e "${RED}Error: GitHub username is required${NC}"
    exit 1
fi

REPO_NAME="ai-finance-tech-dashboard"
REPO_URL="https://github.com/$USERNAME/$REPO_NAME"

echo ""
echo -e "${YELLOW}Setting up repository: $REPO_URL${NC}"
echo ""

# Check if git is initialized
if [ -d ".git" ]; then
    echo -e "${YELLOW}Git already initialized. Checking remote...${NC}"
    git remote -v
else
    echo "Initializing git repository..."
    git init
    git branch -M main
fi

# Add all files
echo "Adding files to git..."
git add .

# Commit
echo "Creating initial commit..."
git commit -m "Initial commit: AI Finance Tech Dashboard

- Main dashboard with 3-column layout
- Archive system with searchable history
- Database-driven pipeline
- Automated deployment to GitHub Pages
- Podcast and newsletter analysis
- Weighted scoring system"

# Add remote
if git remote | grep -q "origin"; then
    echo "Remote 'origin' already exists. Updating..."
    git remote set-url origin "$REPO_URL"
else
    echo "Adding remote origin..."
    git remote add origin "$REPO_URL"
fi

# Instructions for next steps
echo ""
echo "=========================================="
echo -e "${GREEN}✓ Local setup complete!${NC}"
echo "=========================================="
echo ""
echo "Next steps:"
echo ""
echo "1. ${YELLOW}Create the repository on GitHub:${NC}"
echo "   Visit: https://github.com/new"
echo "   - Repository name: $REPO_NAME"
echo "   - Make it Public"
echo "   - Don't initialize with README"
echo ""
echo "2. ${YELLOW}Push the code:${NC}"
echo "   git push -u origin main"
echo ""
echo "3. ${YELLOW}Enable GitHub Pages:${NC}"
echo "   - Go to: https://github.com/$USERNAME/$REPO_NAME/settings/pages"
echo "   - Under 'Source', select 'GitHub Actions'"
echo ""
echo "4. ${YELLOW}Wait 2-3 minutes for deployment${NC}"
echo ""
echo "5. ${YELLOW}View your site:${NC}"
echo "   https://$USERNAME.github.io/$REPO_NAME"
echo ""
echo "=========================================="
echo "Optional: Set up custom domain"
echo "=========================================="
echo ""
echo "To use a custom domain (e.g., scarcityabundance.com):"
echo "1. Add CNAME file in site/ directory:"
echo "   echo 'scarcityabundance.com' > site/CNAME"
echo "2. Configure DNS with your provider"
echo "3. Enable HTTPS in GitHub Pages settings"
echo ""
echo "=========================================="

# Save username for future use
echo "$USERNAME" > .github_username
echo -e "${GREEN}GitHub username saved to .github_username${NC}"

exit 0