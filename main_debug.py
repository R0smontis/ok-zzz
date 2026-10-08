from src.performance_policy import configure_native_threads
configure_native_threads()
import ok
from src.config import config

if __name__ == '__main__':
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
