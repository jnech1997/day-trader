#!/bin/bash

###############################################################################
# TERMINAL TRADING DASHBOARD
# Real-time monitoring of paper/live trading in your terminal
# 
# Usage: ./trading_dashboard.sh [paper|live]
# Example: ./trading_dashboard.sh paper
###############################################################################

# Configuration
DB_PATH="./trader_day.sqlite"
REFRESH_INTERVAL=5  # seconds
MODE="${1:-paper}"  # Default to paper mode

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Symbols
CHECK="✓"
CROSS="✗"
ARROW_UP="↑"
ARROW_DOWN="↓"
BULLET="•"

###############################################################################
# HELPER FUNCTIONS
###############################################################################

clear_screen() {
    clear
    tput cup 0 0
}

print_header() {
    local width=80
    local title="TRADING DASHBOARD"
    local mode_display
    
    if [ "$MODE" = "live" ]; then
        mode_display="${RED}🔴 LIVE MODE - REAL MONEY${NC}"
    else
        mode_display="${BLUE}📄 PAPER MODE - SIMULATION${NC}"
    fi
    
    echo -e "${BOLD}${CYAN}"
    printf '═%.0s' $(seq 1 $width)
    echo -e "${NC}"
    
    printf "${BOLD}${WHITE}%*s${NC}\n" $(((${#title}+$width)/2)) "$title"
    printf "${mode_display}\n"
    
    echo -e "${BOLD}${CYAN}"
    printf '═%.0s' $(seq 1 $width)
    echo -e "${NC}"
    
    printf "${GRAY}Last Update: $(date '+%Y-%m-%d %H:%M:%S')${NC}\n"
    printf "${GRAY}Press Ctrl+C to exit | Auto-refresh: ${REFRESH_INTERVAL}s${NC}\n\n"
}

check_database() {
    if [ ! -f "$DB_PATH" ]; then
        echo -e "${RED}${CROSS} Database not found: $DB_PATH${NC}"
        echo -e "${YELLOW}Run the trading agent first to create the database${NC}"
        exit 1
    fi
}

check_sqlite() {
    if ! command -v sqlite3 &> /dev/null; then
        echo -e "${RED}${CROSS} sqlite3 not found${NC}"
        echo -e "${YELLOW}Install with: brew install sqlite (Mac) or apt-get install sqlite3 (Linux)${NC}"
        exit 1
    fi
}

###############################################################################
# DATABASE QUERIES
###############################################################################

get_open_positions_count() {
    sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM positions;" 2>/dev/null || echo "0"
}

get_open_positions() {
    sqlite3 -header -column "$DB_PATH" \
    "SELECT 
        symbol,
        UPPER(side) AS side,
        ROUND(entry_price, 2) AS entry,
        ROUND(qty_remaining, 4) AS qty,
        ROUND(stop, 2) AS stop,
        ROUND(take, 2) AS target,
        broker,
        substr(entry_time, 1, 16) AS opened
     FROM positions
     ORDER BY entry_time DESC
     LIMIT 10;"
}

get_total_trades() {
    sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trades;" 2>/dev/null || echo "0"
}

get_win_rate() {
    local result=$(sqlite3 "$DB_PATH" \
        "SELECT ROUND(CAST(SUM(CASE WHEN r_mult > 0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) * 100, 1) 
         FROM trades;" 2>/dev/null)
    echo "${result:-0.0}"
}

get_total_pnl() {
    local result=$(sqlite3 "$DB_PATH" "SELECT ROUND(SUM(pnl), 2) FROM trades;" 2>/dev/null)
    echo "${result:-0.00}"
}

get_avg_r() {
    local result=$(sqlite3 "$DB_PATH" "SELECT ROUND(AVG(r_mult), 3) FROM trades;" 2>/dev/null)
    echo "${result:-0.000}"
}

get_avg_win() {
    local result=$(sqlite3 "$DB_PATH" \
        "SELECT ROUND(AVG(r_mult), 3) FROM trades WHERE r_mult > 0;" 2>/dev/null)
    echo "${result:-0.000}"
}

get_avg_loss() {
    local result=$(sqlite3 "$DB_PATH" \
        "SELECT ROUND(AVG(r_mult), 3) FROM trades WHERE r_mult <= 0;" 2>/dev/null)
    echo "${result:-0.000}"
}

get_best_trade() {
    local result=$(sqlite3 "$DB_PATH" "SELECT ROUND(MAX(r_mult), 3) FROM trades;" 2>/dev/null)
    echo "${result:-0.000}"
}

get_worst_trade() {
    local result=$(sqlite3 "$DB_PATH" "SELECT ROUND(MIN(r_mult), 3) FROM trades;" 2>/dev/null)
    echo "${result:-0.000}"
}

get_recent_trades() {
    sqlite3 -header -column "$DB_PATH" \
        "SELECT symbol, side, ROUND(entry_price, 2) as entry, 
         ROUND(exit_price, 2) as exit, ROUND(r_mult, 2) as R, 
         ROUND(pnl, 2) as pnl, reason,
         substr(exit_time, 1, 16) as time
         FROM trades 
         ORDER BY exit_time DESC 
         LIMIT 10;" 2>/dev/null
}

get_symbol_performance() {
    sqlite3 -header -column "$DB_PATH" \
        "SELECT symbol, 
         COUNT(*) as trades,
         ROUND(CAST(SUM(CASE WHEN r_mult > 0 THEN 1 ELSE 0 END) AS FLOAT) / COUNT(*) * 100, 1) as win_rate,
         ROUND(SUM(pnl), 2) as total_pnl
         FROM trades 
         GROUP BY symbol
         ORDER BY total_pnl DESC;" 2>/dev/null
}

get_long_short_stats() {
    # Long stats
    local long_trades=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trades WHERE side='long';" 2>/dev/null || echo "0")
    local long_wins=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trades WHERE side='long' AND r_mult > 0;" 2>/dev/null || echo "0")
    local long_pnl=$(sqlite3 "$DB_PATH" "SELECT ROUND(SUM(pnl), 2) FROM trades WHERE side='long';" 2>/dev/null)
    long_pnl="${long_pnl:-0.00}"
    
    # Short stats
    local short_trades=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trades WHERE side='short';" 2>/dev/null || echo "0")
    local short_wins=$(sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM trades WHERE side='short' AND r_mult > 0;" 2>/dev/null || echo "0")
    local short_pnl=$(sqlite3 "$DB_PATH" "SELECT ROUND(SUM(pnl), 2) FROM trades WHERE side='short';" 2>/dev/null)
    short_pnl="${short_pnl:-0.00}"
    
    # Calculate win rates
    local long_wr="0.0"
    if [ "$long_trades" -gt 0 ] 2>/dev/null; then
        long_wr=$(echo "scale=1; $long_wins * 100 / $long_trades" | bc 2>/dev/null || echo "0.0")
    fi
    
    local short_wr="0.0"
    if [ "$short_trades" -gt 0 ] 2>/dev/null; then
        short_wr=$(echo "scale=1; $short_wins * 100 / $short_trades" | bc 2>/dev/null || echo "0.0")
    fi
    
    echo "$long_trades|$long_wr|$long_pnl|$short_trades|$short_wr|$short_pnl"
}

###############################################################################
# DISPLAY FUNCTIONS
###############################################################################

print_section_header() {
    local title="$1"
    echo -e "\n${BOLD}${YELLOW}${title}${NC}"
    printf "${GRAY}─%.0s${NC}" $(seq 1 80)
    echo
}

print_metric() {
    local label="$1"
    local value="$2"
    local color="$3"
    
    printf "${WHITE}%-20s${NC} ${color}%s${NC}\n" "$label:" "$value"
}

print_open_positions() {
    print_section_header "📊 OPEN POSITIONS"
    
    local count=$(get_open_positions_count)
    
    if [ "$count" -eq 0 ]; then
        echo -e "${GRAY}No open positions${NC}"
        return
    fi
    
    echo -e "${WHITE}Count: ${GREEN}$count${NC}\n"
    
    # Get and display positions
    get_open_positions | while IFS= read -r line; do
        if [[ "$line" == *"symbol"* ]]; then
            # Header line
            echo -e "${BOLD}${CYAN}$line${NC}"
        elif [[ "$line" == *"long"* ]]; then
            echo -e "${GREEN}$line${NC}"
        elif [[ "$line" == *"short"* ]]; then
            echo -e "${RED}$line${NC}"
        else
            echo -e "${WHITE}$line${NC}"
        fi
    done
}

print_performance_metrics() {
    print_section_header "📈 PERFORMANCE METRICS"
    
    local total=$(get_total_trades)
    local win_rate=$(get_win_rate)
    local total_pnl=$(get_total_pnl)
    local avg_r=$(get_avg_r)
    
    # Handle empty values for comparisons
    win_rate="${win_rate:-0.0}"
    total_pnl="${total_pnl:-0.00}"
    avg_r="${avg_r:-0.000}"
    
    # Determine colors (with error handling)
    local pnl_color=$RED
    if [[ "$total_pnl" != "" ]] && (( $(echo "$total_pnl > 0" | bc -l 2>/dev/null || echo "0") )); then
        pnl_color=$GREEN
    fi
    
    local r_color=$RED
    if [[ "$avg_r" != "" ]] && (( $(echo "$avg_r > 0" | bc -l 2>/dev/null || echo "0") )); then
        r_color=$GREEN
    fi
    
    local wr_color=$RED
    if [[ "$win_rate" != "" ]]; then
        if (( $(echo "$win_rate >= 50" | bc -l 2>/dev/null || echo "0") )); then
            wr_color=$GREEN
        elif (( $(echo "$win_rate >= 40" | bc -l 2>/dev/null || echo "0") )); then
            wr_color=$YELLOW
        fi
    fi
    
    # First row
    printf "${WHITE}%-20s${NC} ${CYAN}%s${NC}     " "Total Trades:" "$total"
    printf "${WHITE}%-20s${NC} ${wr_color}%s%%${NC}\n" "Win Rate:" "$win_rate"
    
    # Second row
    printf "${WHITE}%-20s${NC} ${pnl_color}\$%s${NC}     " "Total P&L:" "$total_pnl"
    printf "${WHITE}%-20s${NC} ${r_color}%sR${NC}\n" "Average R:" "$avg_r"
    
    # Third row
    local avg_win=$(get_avg_win)
    local avg_loss=$(get_avg_loss)
    avg_win="${avg_win:-0.000}"
    avg_loss="${avg_loss:-0.000}"
    printf "${WHITE}%-20s${NC} ${GREEN}%sR${NC}     " "Avg Win:" "$avg_win"
    printf "${WHITE}%-20s${NC} ${RED}%sR${NC}\n" "Avg Loss:" "$avg_loss"
    
    # Fourth row
    local best=$(get_best_trade)
    local worst=$(get_worst_trade)
    best="${best:-0.000}"
    worst="${worst:-0.000}"
    printf "${WHITE}%-20s${NC} ${GREEN}%sR${NC}     " "Best Trade:" "$best"
    printf "${WHITE}%-20s${NC} ${RED}%sR${NC}\n" "Worst Trade:" "$worst"
}

print_strategy_stats() {
    print_section_header "🎯 STRATEGY PERFORMANCE"
    
    local stats=$(get_long_short_stats)
    IFS='|' read -r long_trades long_wr long_pnl short_trades short_wr short_pnl <<< "$stats"
    
    # Long stats
    local long_pnl_color=$RED
    if (( $(echo "$long_pnl > 0" | bc -l 2>/dev/null || echo "0") )); then
        long_pnl_color=$GREEN
    fi
    
    local long_wr_color=$RED
    if (( $(echo "$long_wr >= 50" | bc -l 2>/dev/null || echo "0") )); then
        long_wr_color=$GREEN
    elif (( $(echo "$long_wr >= 40" | bc -l 2>/dev/null || echo "0") )); then
        long_wr_color=$YELLOW
    fi
    
    # Short stats
    local short_pnl_color=$RED
    if (( $(echo "$short_pnl > 0" | bc -l 2>/dev/null || echo "0") )); then
        short_pnl_color=$GREEN
    fi
    
    local short_wr_color=$RED
    if (( $(echo "$short_wr >= 50" | bc -l 2>/dev/null || echo "0") )); then
        short_wr_color=$GREEN
    elif (( $(echo "$short_wr >= 40" | bc -l 2>/dev/null || echo "0") )); then
        short_wr_color=$YELLOW
    fi
    
    printf "${WHITE}%-20s${NC} ${CYAN}%s trades${NC}  ${long_wr_color}%s%% win${NC}  ${long_pnl_color}\$%s${NC}\n" \
        "Long Positions:" "$long_trades" "$long_wr" "$long_pnl"
    
    printf "${WHITE}%-20s${NC} ${CYAN}%s trades${NC}  ${short_wr_color}%s%% win${NC}  ${short_pnl_color}\$%s${NC}\n" \
        "Short Positions:" "$short_trades" "$short_wr" "$short_pnl"
}

print_symbol_performance() {
    print_section_header "💰 PERFORMANCE BY SYMBOL"
    
    get_symbol_performance | while IFS= read -r line; do
        if [[ "$line" == *"symbol"* ]]; then
            # Header
            echo -e "${BOLD}${CYAN}$line${NC}"
        elif [[ "$line" =~ [0-9] ]]; then
            # Data line - color code based on P&L
            if [[ "$line" =~ -[0-9] ]]; then
                echo -e "${RED}$line${NC}"
            else
                echo -e "${GREEN}$line${NC}"
            fi
        else
            echo -e "${WHITE}$line${NC}"
        fi
    done
}

print_recent_trades() {
    print_section_header "📋 RECENT TRADES (Last 10)"
    
    get_recent_trades | while IFS= read -r line; do
        if [[ "$line" == *"symbol"* ]]; then
            # Header
            echo -e "${BOLD}${CYAN}$line${NC}"
        elif [[ "$line" =~ [0-9] ]]; then
            # Data line - color code based on P&L
            if [[ "$line" =~ -[0-9]+\.[0-9]+ ]]; then
                echo -e "${RED}$line${NC}"
            else
                echo -e "${GREEN}$line${NC}"
            fi
        else
            echo -e "${WHITE}$line${NC}"
        fi
    done
}

print_footer() {
    echo -e "\n${BOLD}${CYAN}"
    printf '═%.0s' $(seq 1 80)
    echo -e "${NC}"
    echo -e "${GRAY}Press Ctrl+C to exit | Refreshing in ${REFRESH_INTERVAL}s...${NC}"
}

###############################################################################
# MAIN DASHBOARD
###############################################################################

main_dashboard() {
    clear_screen
    
    print_header
    
    print_open_positions
    
    print_performance_metrics
    
    print_strategy_stats
    
    print_symbol_performance
    
    print_recent_trades
    
    print_footer
}

###############################################################################
# MAIN LOOP
###############################################################################

# Check prerequisites
check_sqlite
check_database

# Trap Ctrl+C
trap 'echo -e "\n${YELLOW}Dashboard stopped${NC}"; exit 0' INT

# Display startup message
echo -e "${CYAN}${BOLD}Starting Trading Dashboard...${NC}"
echo -e "${GRAY}Mode: $MODE${NC}"
echo -e "${GRAY}Database: $DB_PATH${NC}"
sleep 2

# Main loop
while true; do
    main_dashboard
    sleep $REFRESH_INTERVAL
done