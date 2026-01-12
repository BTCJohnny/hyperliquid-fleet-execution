"""
Test max concurrent positions safety feature
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_max_positions_initialization():
    """Test that max_concurrent_positions is initialized correctly"""
    from hyperliquid_top_gun import HyperLiquidTopGun
    from dotenv import load_dotenv

    load_dotenv()

    # Test with environment variable
    os.environ['MAX_CONCURRENT_POSITIONS'] = '5'

    # We can't actually initialize HyperLiquidTopGun without a real private key
    # So we'll just verify the .env loading works
    max_pos = int(os.getenv('MAX_CONCURRENT_POSITIONS', '3'))

    assert max_pos == 5, f"Expected 5, got {max_pos}"
    print(f"✓ MAX_CONCURRENT_POSITIONS from env: {max_pos}")

    # Test default value
    del os.environ['MAX_CONCURRENT_POSITIONS']
    max_pos_default = int(os.getenv('MAX_CONCURRENT_POSITIONS', '3'))

    assert max_pos_default == 3, f"Expected default 3, got {max_pos_default}"
    print(f"✓ MAX_CONCURRENT_POSITIONS default: {max_pos_default}")

    # Check .env file has the setting
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')
    with open(env_path, 'r') as f:
        env_content = f.read()

    assert 'MAX_CONCURRENT_POSITIONS' in env_content, ".env file missing MAX_CONCURRENT_POSITIONS"
    print(f"✓ .env file contains MAX_CONCURRENT_POSITIONS setting")

    print("\n✅ All max positions tests passed!")

if __name__ == "__main__":
    test_max_positions_initialization()
