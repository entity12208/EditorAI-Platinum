#!/usr/bin/env python3
"""
Test script for Distributed Ollama Network
Verifies that coordinator, proxy, and workers are functioning correctly
"""

import asyncio
import aiohttp
import time
import sys
from typing import Optional

COLORS = {
    'GREEN': '\033[92m',
    'RED': '\033[91m',
    'YELLOW': '\033[93m',
    'BLUE': '\033[94m',
    'END': '\033[0m'
}

def print_test(message: str, status: Optional[bool] = None):
    """Print test result"""
    if status is True:
        print(f"{COLORS['GREEN']}✓{COLORS['END']} {message}")
    elif status is False:
        print(f"{COLORS['RED']}✗{COLORS['END']} {message}")
    else:
        print(f"{COLORS['BLUE']}▶{COLORS['END']} {message}")

def print_header(message: str):
    """Print section header"""
    print(f"\n{COLORS['YELLOW']}{'=' * 60}{COLORS['END']}")
    print(f"{COLORS['YELLOW']}{message}{COLORS['END']}")
    print(f"{COLORS['YELLOW']}{'=' * 60}{COLORS['END']}\n")

async def test_coordinator(coordinator_url: str):
    """Test coordinator endpoints"""
    print_header("Testing Coordinator")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Test status endpoint
            print_test("Testing /api/status endpoint...")
            async with session.get(f"{coordinator_url}/api/status", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print_test("Coordinator is running", True)
                    print(f"  Active workers: {data['coordinator']['active_workers']}")
                    print(f"  Total workers: {data['coordinator']['workers']}")
                    
                    if data['coordinator']['active_workers'] == 0:
                        print_test("No active workers found", False)
                        return False
                    
                    return True
                else:
                    print_test(f"Coordinator returned HTTP {resp.status}", False)
                    return False
                    
    except Exception as e:
        print_test(f"Failed to connect to coordinator: {e}", False)
        return False

async def test_proxy(proxy_url: str):
    """Test proxy endpoints"""
    print_header("Testing Proxy")
    
    try:
        async with aiohttp.ClientSession() as session:
            # Test health endpoint
            print_test("Testing /health endpoint...")
            async with session.get(f"{proxy_url}/health", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print_test("Proxy is healthy", True)
                    print(f"  Status: {data['status']}")
                    print(f"  Active workers: {data['active_workers']}")
                    print(f"  Requests processed: {data['requests_processed']}")
                    
                    if data['active_workers'] == 0:
                        print_test("No workers available", False)
                        return False
                    
                    return True
                else:
                    print_test(f"Proxy health check failed: HTTP {resp.status}", False)
                    return False
                    
    except Exception as e:
        print_test(f"Failed to connect to proxy: {e}", False)
        return False

async def test_list_models(proxy_url: str):
    """Test model listing"""
    print_header("Testing Model Listing")
    
    try:
        async with aiohttp.ClientSession() as session:
            print_test("Fetching available models...")
            async with session.get(f"{proxy_url}/api/tags", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get('models', [])
                    
                    if len(models) == 0:
                        print_test("No models available", False)
                        return False
                    
                    print_test(f"Found {len(models)} models", True)
                    for model in models[:5]:  # Show first 5
                        print(f"  - {model['name']}")
                    if len(models) > 5:
                        print(f"  ... and {len(models) - 5} more")
                    
                    return True
                else:
                    print_test(f"Failed to list models: HTTP {resp.status}", False)
                    return False
                    
    except Exception as e:
        print_test(f"Error listing models: {e}", False)
        return False

async def test_generation(proxy_url: str, model: str = "llama2"):
    """Test actual text generation"""
    print_header(f"Testing Generation with {model}")
    
    try:
        async with aiohttp.ClientSession() as session:
            print_test(f"Sending generation request for model '{model}'...")
            
            start_time = time.time()
            
            request_data = {
                "model": model,
                "prompt": "Say 'Hello from distributed Ollama!' and nothing else.",
                "stream": False,
                "options": {
                    "temperature": 0.7,
                    "num_predict": 50
                }
            }
            
            async with session.post(
                f"{proxy_url}/api/generate",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=60)
            ) as resp:
                
                if resp.status == 200:
                    data = await resp.json()
                    elapsed = time.time() - start_time
                    
                    if 'response' in data:
                        print_test(f"Generation successful ({elapsed:.2f}s)", True)
                        print(f"\n  Response: {data['response'][:200]}")
                        if len(data['response']) > 200:
                            print(f"  ... (truncated)")
                        return True
                    else:
                        print_test("Generation returned no response", False)
                        return False
                        
                elif resp.status == 503:
                    print_test("No workers available for this model", False)
                    return False
                    
                else:
                    error_data = await resp.text()
                    print_test(f"Generation failed: HTTP {resp.status}", False)
                    print(f"  Error: {error_data[:200]}")
                    return False
                    
    except asyncio.TimeoutError:
        print_test("Generation timed out (>60s)", False)
        return False
    except Exception as e:
        print_test(f"Generation error: {e}", False)
        return False

async def run_tests(coordinator_url: str, proxy_url: str, test_model: Optional[str] = None):
    """Run all tests"""
    print(f"\n{COLORS['BLUE']}Distributed Ollama Network Test Suite{COLORS['END']}")
    print(f"Coordinator: {coordinator_url}")
    print(f"Proxy: {proxy_url}")
    
    results = {
        'coordinator': False,
        'proxy': False,
        'models': False,
        'generation': False
    }
    
    # Test coordinator
    results['coordinator'] = await test_coordinator(coordinator_url)
    
    if not results['coordinator']:
        print_test("\n⚠ Coordinator test failed. Cannot continue.", None)
        return results
    
    # Test proxy
    results['proxy'] = await test_proxy(proxy_url)
    
    if not results['proxy']:
        print_test("\n⚠ Proxy test failed. Cannot continue.", None)
        return results
    
    # Test model listing
    results['models'] = await test_list_models(proxy_url)
    
    if not results['models']:
        print_test("\n⚠ No models available. Cannot test generation.", None)
        return results
    
    # Get first available model if not specified
    if test_model is None:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{proxy_url}/api/tags") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = data.get('models', [])
                    if models:
                        test_model = models[0]['name']
    
    # Test generation
    if test_model:
        results['generation'] = await test_generation(proxy_url, test_model)
    else:
        print_test("\n⚠ No model specified for generation test.", None)
    
    # Summary
    print_header("Test Summary")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    print(f"Tests passed: {passed}/{total}")
    print(f"Coordinator: {'✓' if results['coordinator'] else '✗'}")
    print(f"Proxy: {'✓' if results['proxy'] else '✗'}")
    print(f"Models: {'✓' if results['models'] else '✗'}")
    print(f"Generation: {'✓' if results['generation'] else '✗'}")
    
    if passed == total:
        print(f"\n{COLORS['GREEN']}All tests passed! ✓{COLORS['END']}")
        return results
    else:
        print(f"\n{COLORS['RED']}Some tests failed. ✗{COLORS['END']}")
        return results

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Test Distributed Ollama Network')
    parser.add_argument('--coordinator', default='http://ollama-coordinator.onrender.com', help='Coordinator URL')
    parser.add_argument('--proxy', default='http://ollama-proxy-sh88.onrender.com', help='Proxy URL')
    parser.add_argument('--model', help='Model to test (default: first available)')
    
    args = parser.parse_args()
    
    results = await run_tests(args.coordinator, args.proxy, args.model)
    
    # Exit with error code if any test failed
    if not all(results.values()):
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
