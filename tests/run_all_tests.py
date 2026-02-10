#!/usr/bin/env python
"""
Master test runner for Meshtastic-Matrix Bridge
Runs all test suites and provides comprehensive summary
"""

import subprocess
import sys
import os
from pathlib import Path
from dataclasses import dataclass
from typing import List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

@dataclass
class TestResult:
    name: str
    passed: int
    failed: int
    errors: int
    skipped: int
    total: int
    success: bool

def run_test_file(filename: str) -> TestResult:
    """Run a single test file and parse results"""
    print(f"\n{'='*60}")
    print(f"Running: {filename}")
    print('='*60)
    
    try:
        # Set PYTHONPATH to include project root
        env = os.environ.copy()
        env['PYTHONPATH'] = str(project_root)
        
        result = subprocess.run(
            [sys.executable, filename],
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        
        output = result.stdout + result.stderr
        print(output)
        
        # Parse unittest output
        passed = failed = errors = skipped = 0
        total = 0
        success = result.returncode == 0
        
        # Look for summary line like "Ran 13 tests in 0.052s"
        for line in output.split('\n'):
            if line.startswith('Ran '):
                parts = line.split()
                if len(parts) >= 2:
                    total = int(parts[1])
            elif 'FAILED' in line:
                # Parse: "FAILED (failures=1, errors=2)"
                if 'failures=' in line:
                    failed_str = line.split('failures=')[1].split(',')[0].split(')')[0]
                    failed = int(failed_str)
                if 'errors=' in line:
                    errors_str = line.split('errors=')[1].split(',')[0].split(')')[0]
                    errors = int(errors_str)
            elif line == 'OK':
                passed = total
        
        if total > 0 and passed == 0 and failed == 0 and errors == 0:
            # All tests passed if OK and no failures/errors
            passed = total
        elif total > 0:
            # Calculate passed from total minus failures/errors
            passed = total - failed - errors - skipped
        
        return TestResult(
            name=filename,
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            total=total,
            success=success
        )
        
    except subprocess.TimeoutExpired:
        print(f"❌ TIMEOUT: {filename} took too long")
        return TestResult(filename, 0, 0, 1, 0, 0, False)
    except Exception as e:
        print(f"❌ ERROR running {filename}: {e}")
        return TestResult(filename, 0, 0, 1, 0, 0, False)


def print_summary(results: List[TestResult]):
    """Print comprehensive test summary"""
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    total_passed = sum(r.passed for r in results)
    total_failed = sum(r.failed for r in results)
    total_errors = sum(r.errors for r in results)
    total_skipped = sum(r.skipped for r in results)
    total_tests = sum(r.total for r in results)
    
    success_count = sum(1 for r in results if r.success)
    total_files = len(results)
    
    print(f"\nTest Files: {success_count}/{total_files} passed")
    print(f"\nIndividual Tests:")
    print(f"  ✅ Passed:  {total_passed}")
    print(f"  ❌ Failed:  {total_failed}")
    print(f"  ⚠️  Errors:  {total_errors}")
    print(f"  ⏭️  Skipped: {total_skipped}")
    print(f"  📊 Total:   {total_tests}")
    
    if total_tests > 0:
        pass_rate = (total_passed / total_tests) * 100
        print(f"\nPass Rate: {pass_rate:.1f}%")
    
    print("\nPer-File Results:")
    for r in results:
        status = "✅" if r.success else "❌"
        print(f"  {status} {r.name:40s} {r.passed:3d}/{r.total:3d} passed", end="")
        if r.failed > 0:
            print(f", {r.failed} failed", end="")
        if r.errors > 0:
            print(f", {r.errors} errors", end="")
        print()
    
    print("="*60)
    
    # Return overall success
    return total_failed == 0 and total_errors == 0 and total_tests > 0


def main():
    # Get the tests directory path
    tests_dir = Path(__file__).parent
    
    test_files = [
        'test_bridge.py',
        'test_coverage_extended.py',
        'test_database.py',
        'test_matrix_bot.py',
        'test_meshtastic_interface.py',
        'test_mqtt_client.py',
        'test_bridge_advanced.py',
    ]
    
    print("="*60)
    print("MESHTASTIC-MATRIX BRIDGE TEST SUITE")
    print("="*60)
    print(f"Running {len(test_files)} test files...")
    
    results = []
    for test_file in test_files:
        test_path = tests_dir / test_file
        result = run_test_file(str(test_path))
        results.append(result)
    
    all_pass = print_summary(results)
    
    sys.exit(0 if all_pass else 1)


if __name__ == '__main__':
    main()
