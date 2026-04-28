import paramiko
import sys

def audit_remote(host, username, password):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, username=username, password=password, timeout=10)
        
        commands = {
            "Host Info": "hostname; uname -a",
            "Docker Status": "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null",
            "Nginx Status": "systemctl status nginx --no-pager 2>/dev/null || (ps aux | grep nginx | grep -v grep)",
            "Nginx Config List": "ls -R /etc/nginx/ 2>/dev/null",
            "Nginx Data List": "ls -R /data/nginx/ 2>/dev/null",
            "DuckDNS Config Search": "grep -r 'nxchieu.duckdns.org' /etc/nginx/ 2>/dev/null || grep -r 'nxchieu.duckdns.org' /data/nginx/ 2>/dev/null",
            "Listening Ports": "netstat -tulpn 2>/dev/null || ss -tulpn 2>/dev/null"
        }
        
        for name, cmd in commands.items():
            print(f"\n--- {name} ---")
            stdin, stdout, stderr = client.exec_command(cmd)
            print(stdout.read().decode('utf-8', 'ignore'))
            err = stderr.read().decode('utf-8', 'ignore')
            if err: print(f"Error: {err}")
            
    except Exception as e:
        print(f"SSH Failed: {str(e)}")
    finally:
        client.close()

if __name__ == "__main__":
    audit_remote("10.25.7.116", "user", "Admin@12345")
