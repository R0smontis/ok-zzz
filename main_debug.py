import ok
from src.config import config

if __name__ == '__main__':
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
