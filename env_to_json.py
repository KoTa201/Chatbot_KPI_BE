import json
import re


def env_to_json(env_file=".env", output_file=None):
    env_vars = {}

    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()

            # Skip komentar dan baris kosong
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE
            match = re.match(r'^([^=]+)=(.*)$', line)
            if match:
                key = match.group(1).strip()
                value = match.group(2).strip()

                # Hapus quote di awal/akhir value jika ada
                value = value.strip('"').strip("'")

                env_vars[key] = value

    json_output = json.dumps(env_vars, indent=2)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(json_output)
        print(f"✅ Saved to {output_file}")
    else:
        print(json_output)

    return env_vars


if __name__ == "__main__":
    env_to_json(".env")