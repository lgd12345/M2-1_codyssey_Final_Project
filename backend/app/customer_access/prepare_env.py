"""Prepare a private container env file; never executed by app startup."""
import os
from pathlib import Path
import secrets


def prepare(destination, template):
    # Exclusive creation preserves an existing deployment key and app password.
    content = template.read_text(encoding='utf-8')
    if content.count('\nCUSTOMER_ACCESS_SECRET=\n') != 1:
        raise ValueError('Expected one empty internal-secret setting')
    content = content.replace('\nCUSTOMER_ACCESS_SECRET=\n',
                              '\nCUSTOMER_ACCESS_SECRET='+secrets.token_urlsafe(48)+'\n')
    destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    descriptor = os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w',encoding='utf-8',newline='\n') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def main():
    backend = Path(__file__).resolve().parents[2]
    target = backend/'private-data/customer-access.env'
    try:
        prepare(target,backend/'customer-access.env.example')
    except FileExistsError:
        raise SystemExit('Existing private settings preserved; no file was overwritten.')
    print('Private settings prepared: backend/private-data/customer-access.env')
    print('Internal verification secret generated. Fill only CUSTOMER_SMTP_PASSWORD, then inject this env file into the server container.')


if __name__=='__main__':
    main()
