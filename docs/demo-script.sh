#!/usr/bin/env bash
# Demo script for VHS recording — simulates the Distill flow

dim='\033[2m'
bold='\033[1m'
green='\033[32m'
yellow='\033[33m'
cyan='\033[36m'
reset='\033[0m'

sleep 0.3

echo -e "${dim}# You type freely into Claude Code:${reset}"
echo ""
sleep 0.5
echo -e "${bold}${yellow}You:${reset} \"I spent 3 days trying Redis pub/sub and it's garbage."
echo -e "      Bob suggested Kafka but I ignored him.\""
sleep 2

echo ""
echo -e "${dim}  ⣾ Ollama distilling locally...${reset}"
sleep 0.8
echo -e "${dim}  ⣽ Ollama distilling locally...${reset}"
sleep 0.8

echo ""
echo -e "${dim}# Team DB gets:${reset}"
echo ""
echo -e "${bold}${green}Saved:${reset} \"Redis pub/sub is unsuitable for the event-bus use case"
echo -e "        due to message loss under load. Evaluate Kafka or NATS."
echo -e "        (Q1 2026)\""

echo ""
echo -e "${cyan}No author. No frustration. No names.${reset}"

sleep 3
