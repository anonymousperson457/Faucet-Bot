#!/usr/bin/env python3
import os
import time
import random
import requests
from web3 import Web3
from eth_account import Account
import json
from requests.exceptions import ReadTimeout, ConnectionError
from stem import Signal
from stem.control import Controller

class SepoliaFaucetBot:
    def __init__(self):
        self.rpc_url = "https://eth-sepolia.public.blastapi.io"
        self.faucet_url = "https://faucet.chainplatform.co/api/ethereum-sepolia/faucet"
        self.request_delay = 1
        
        self.tor_proxy = {
            'http': 'socks5h://localhost:9050',
            'https': 'socks5h://localhost:9050'
        }
        
        self.w3 = Web3(Web3.HTTPProvider(self.rpc_url))
        
        if not self.w3.is_connected():
            print("❌ Failed to connect to Sepolia network")
            exit(1)
        else:
            print("✅ Connected to Sepolia network")
    
    def generate_random_account(self):
        """Generate a random private key and derive ETH address"""
        private_key = os.urandom(32).hex()
        account = Account.from_key(private_key)
        return {
            'private_key': private_key,
            'address': account.address
        }
    
    def get_balance(self, address):
        """Get ETH balance for an address"""
        try:
            balance_wei = self.w3.eth.get_balance(address)
            balance_eth = self.w3.from_wei(balance_wei, 'ether')
            return float(balance_eth)
        except Exception as e:
            print(f"❌ Error getting balance for {address}: {e}")
            return 0
    
    def change_tor_identity(self):
        """Request a new Tor identity (unique IP address)"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                with Controller.from_port(port=9051) as controller:
                    controller.authenticate()
                    controller.signal(Signal.NEWNYM)
                    print(f"🔄 Changed to new Tor identity (unique IP) on attempt {attempt + 1}")
                    time.sleep(3)
                    return True
            except Exception as e:
                print(f"❌ Error changing Tor identity on attempt {attempt + 1}: {e}")
                if attempt < max_attempts - 1:
                    print(f"🔄 Retrying Tor identity change in {self.request_delay} seconds...")
                    time.sleep(self.request_delay)
        print("❌ Failed to change Tor identity after maximum attempts - proceeding with current IP")
        return False
    
    def request_faucet_funds(self, address):
        """Request funds from the faucet API through Tor with a unique IP"""
        try:
            print(f"🔄 Preparing new IP for faucet request to {address}...")
            if not self.change_tor_identity():
                print("⚠️ Proceeding with faucet request despite Tor identity change failure")
            
            print(f"🚰 Requesting funds for {address} with new IP...")
            
            payload = {
                'walletAddress': address,
                'turnstileToken': ''
            }
            
            headers = {
                'Content-Type': 'application/json',
                'Accept': '*/*',
                'User-Agent': 'Mozilla/5.0 (Linux; Android 13; sdk_gphone_x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/103.0.0.0 Mobile Safari/537.36',
                'Origin': 'https://faucet.chainplatform.co',
                'Referer': 'https://faucet.chainplatform.co/faucets/ethereum-sepolia/',
                'sec-ch-ua': '".Not/A)Brand";v="99", "Google Chrome";v="103", "Chromium";v="103"',
                'sec-ch-ua-mobile': '?1',
                'sec-ch-ua-platform': '"Android"',
                'sec-fetch-site': 'same-origin',
                'sec-fetch-mode': 'cors',
                'sec-fetch-dest': 'empty',
                'accept-encoding': 'gzip, deflate, br',
                'accept-language': 'en-US,en;q=0.9'
            }
            
            response = requests.post(self.faucet_url, json=payload, headers=headers, timeout=30, proxies=self.tor_proxy)
            print(f"  Response: {response.status_code}")
            
            if response.status_code == 200:
                print("✅ Faucet request successful")
                return True, response.content
            else:
                print(f"❌ Faucet request failed: {response.status_code}")
                print(f"  Raw response: {response.content}")
                return False, response.content
                
        except ReadTimeout:
            print(f"❌ Error requesting faucet funds: Read timeout after 30 seconds")
            return False, b"TIMEOUT"
        except ConnectionError as e:
            if "Connection reset by peer" in str(e):
                print(f"❌ Error requesting faucet funds: Connection reset by peer")
                return False, b"CONNECTION_RESET"
            elif "Max retries exceeded with url" in str(e):
                print(f"❌ Error requesting faucet funds: Max retries exceeded with url")
                return False, b"MAX_RETRIES_EXCEEDED"
            else:
                print(f"❌ Error requesting faucet funds: {e}")
                return False, b""
        except Exception as e:
            print(f"❌ Error requesting faucet funds: {e}")
            return False, b""
    
    def check_balance_and_transfer(self, temp_private_key, temp_address, recipient_address, initial_balance, check_attempts=10):
        """Check balance for a specified number of attempts and transfer funds if received"""
        funds_received = False
        current_balance = 0
        for i in range(check_attempts):
            current_balance = self.get_balance(temp_address)
            if current_balance > initial_balance:
                funds_received = True
                print(f"✅ Funds received on check {i+1}! Balance: {current_balance} ETH")
                break
            print(f"⏳ Checking balance (Attempt {i+1}/{check_attempts})... Current balance: {current_balance} ETH")
            time.sleep(1)
        
        if funds_received:
            retry_count = 0
            while True:
                retry_count += 1
                print(f"🔄 Attempting transfer (Attempt #{retry_count})...")
                if self.transfer_funds(temp_private_key, temp_address, recipient_address, current_balance):
                    print("✅ Funds successfully transferred to recipient!")
                    return True
                else:
                    print(f"❌ Transfer failed - retrying in {self.request_delay} seconds...")
                    time.sleep(self.request_delay)
                    if self.get_balance(temp_address) <= initial_balance:
                        print("❌ Funds no longer available - stopping retries")
                        return False
        return False
    
    def transfer_funds(self, from_private_key, from_address, to_address, amount_eth):
        """Transfer the full amount (minus gas fees) from one address to another"""
    try:
        nonce = self.w3.eth.get_transaction_count(from_address)
        gas_price = self.w3.eth.gas_price
        gas_limit = 21000
        
        gas_cost_wei = gas_limit * gas_price
        gas_cost_eth = self.w3.from_wei(gas_cost_wei, 'ether')
        
        balance_wei = self.w3.eth.get_balance(from_address)
        balance_eth = self.w3.from_wei(balance_wei, 'ether')
        
        send_amount_wei = balance_wei - gas_cost_wei
        send_amount_eth = self.w3.from_wei(send_amount_wei, 'ether')
        
        if send_amount_wei <= 0:
            print(f"❌ Insufficient funds for transfer. Balance: {balance_eth:.18f} ETH, Gas cost: {gas_cost_eth:.18f} ETH")
            return False
        
        transaction = {
            'nonce': nonce,
            'to': to_address,
            'value': send_amount_wei,
            'gas': gas_limit,
            'gasPrice': gas_price,
        }
        
        signed_txn = self.w3.eth.account.sign_transaction(transaction, from_private_key)
        tx_hash = self.w3.eth.send_raw_transaction(signed_txn.rawTransaction)  # Changed from raw_transaction to rawTransaction
        
        print(f"💸 Transfer initiated! TX Hash: {tx_hash.hex()}")
        print(f"💰 Sent {send_amount_eth:.18f} ETH to {to_address}")
        
        print("⏳ Waiting for 1 block confirmation...")
        tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        
        if tx_receipt.status == 1:
            print(f"✅ Transfer confirmed! Block: {tx_receipt.blockNumber}")
            return True
        else:
            print("❌ Transfer failed!")
            return False
                
    except Exception as e:
        print(f"❌ Error transferring funds: {e}")
        return False
    
    def wait_for_funds_and_transfer(self, temp_private_key, temp_address, recipient_address, initial_balance, timeout=300):
        """Wait for funds to arrive and immediately transfer them with retries"""
        print(f"⏳ Waiting for funds to arrive at {temp_address}...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            current_balance = self.get_balance(temp_address)
            
            if current_balance > initial_balance:
                print(f"✅ Funds received! Balance: {current_balance} ETH")
                
                retry_count = 0
                while True:
                    retry_count += 1
                    print(f"🔄 Attempting transfer (Attempt #{retry_count})...")
                    if self.transfer_funds(temp_private_key, temp_address, recipient_address, current_balance):
                        print("✅ Funds successfully transferred to recipient!")
                        return True
                    else:
                        print(f"❌ Transfer failed - retrying in {self.request_delay} seconds...")
                        time.sleep(self.request_delay)
                        if self.get_balance(temp_address) <= initial_balance:
                            print("❌ Funds no longer available - stopping retries")
                            return False
            
            print(f"⏳ Checking... Current balance: {current_balance} ETH")
            time.sleep(1)
        
        print(f"❌ Timeout waiting for funds")
        return False
    
    def run_bot(self, recipient_address):
        """Main bot loop"""
        print(f"🤖 Starting Sepolia Faucet Bot")
        print(f"📍 Recipient address: {recipient_address}")
        print(f"{'='*50}")
        
        cycle = 1
        temp_address = None
        temp_private_key = None
        reuse = False
        
        while True:
            try:
                print(f"\n🔄 Cycle #{cycle}")
                
                if not reuse:
                    account = self.generate_random_account()
                    temp_address = account['address']
                    temp_private_key = account['private_key']
                else:
                    reuse = False
                    print(f"🔄 Reusing address from previous cycle: {temp_address}")
                
                print(f"🎲 Generated temporary address: {temp_address}")
                print(f"🔑 Private key: {temp_private_key[2:] if temp_private_key.startswith('0x') else temp_private_key}")
                
                initial_balance = self.get_balance(temp_address)
                print(f"💰 Initial balance: {initial_balance} ETH")
                
                while True:
                    success, response_content = self.request_faucet_funds(temp_address)
                    if success:
                        if self.wait_for_funds_and_transfer(temp_private_key, temp_address, recipient_address, initial_balance):
                            print(f"✅ Cycle #{cycle} completed successfully! Moving to next cycle...")
                            cycle += 1
                            time.sleep(self.request_delay)
                            break
                        else:
                            print(f"❌ Cycle #{cycle} failed at transfer step - retrying same address...")
                            time.sleep(2)
                            continue
                    else:
                        if b"MAX_RETRIES_EXCEEDED" in response_content:
                            print(f"⚠️ Max retries exceeded with url detected - reusing address in next cycle")
                            reuse = True
                            cycle += 1
                            time.sleep(self.request_delay)
                            break
                        elif b"TRANSACTION_REPLACED" in response_content:
                            print(f"⚠️ TRANSACTION_REPLACED detected - reusing address in next cycle")
                            reuse = True
                            cycle += 1
                            time.sleep(self.request_delay)
                            break
                        elif b"REPLACEMENT_UNDERPRICED" in response_content:
                            print(f"⚠️ REPLACEMENT_UNDERPRICED detected - reusing address in next cycle")
                            reuse = True
                            cycle += 1
                            time.sleep(self.request_delay)
                            break
                        elif b"RATE_LIMIT" in response_content:
                            print(f"⚠️ RATE_LIMIT detected - checking balance for 10 times...")
                            if self.check_balance_and_transfer(temp_private_key, temp_address, recipient_address, initial_balance):
                                # Recheck balance for second time after successful transfer
                                print(f"🔄 Rechecking balance for second time after transfer...")
                                initial_balance = self.get_balance(temp_address)  # Update initial balance
                                if self.check_balance_and_transfer(temp_private_key, temp_address, recipient_address, initial_balance):
                                    print(f"✅ Second transfer successful!")
                                else:
                                    print(f"❌ No additional funds received on second check")
                            else:
                                print(f"❌ No funds received after 10 checks - moving to next cycle with new address")
                            cycle += 1
                            time.sleep(self.request_delay)
                            break
                        elif b"Temporarily forbidden due to suspicious requests" in response_content:
                            print(f"⚠️ Temporarily forbidden due to suspicious requests detected - reusing address in next cycle")
                            reuse = True
                            cycle += 1
                            time.sleep(self.request_delay)
                            break
                        elif b"ACCESS_RESTRICTED" in response_content:
                            print(f"⚠️ ACCESS_RESTRICTED detected - retrying same address in {self.request_delay} seconds...")
                            time.sleep(self.request_delay)
                            continue
                        elif b"TIMEOUT" in response_content:
                            print(f"⚠️ Request timeout detected - retrying same address in {self.request_delay} seconds...")
                            time.sleep(self.request_delay)
                            continue
                        elif b"CONNECTION_RESET" in response_content:
                            print(f"⚠️ Connection reset detected - retrying same address in {self.request_delay} seconds...")
                            time.sleep(self.request_delay)
                            continue
                        else:
                            print(f"❌ Cycle #{cycle} failed at faucet request")
                            cycle += 1
                            time.sleep(self.request_delay)
                            break
                
                print(f"⚡ Next cycle in {self.request_delay} seconds...")
                
            except KeyboardInterrupt:
                print(f"\n🛑 Bot stopped by user")
                break
            except Exception as e:
                print(f"❌ Unexpected error in cycle #{cycle}: {e}")
                print(f"⚡ Retrying in {self.request_delay} seconds...")
                time.sleep(self.request_delay)

def main():
    print("🌊 Sepolia ETH Auto Faucet Bot")
    print()
    
    recipient = input("Enter recipient ETH address: ").strip()
    
    if not Web3.is_address(recipient):
        print("❌ Invalid Ethereum address!")
        return
    
    recipient = Web3.to_checksum_address(recipient)
    
    bot = SepoliaFaucetBot()
    bot.run_bot(recipient)

if __name__ == "__main__":
    main()
