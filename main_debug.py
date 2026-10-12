from src.runtime.performance_policy import configure_native_threads
configure_native_threads()
import ok
from src.config import config

if __name__ == '__main__':
    from src.controls.interaction import migrate_saved_interaction
    migrate_saved_interaction(config['config_folder'])
    config['debug'] = True
    ok = ok.OK(config)
    ok.start()
