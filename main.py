import sys
import os

if __name__ == '__main__':
    from src.runtime.performance_policy import configure_native_threads
    configure_native_threads()
    from src.runtime.startup import ensure_output_streams, prepare_runtime_directory
    prepare_runtime_directory()
    check_output = None
    if '--check-package-output' in sys.argv:
        index = sys.argv.index('--check-package-output')
        check_output = sys.argv[index + 1]
    ensure_output_streams(check_output)
    if '--live-client' in sys.argv:
        from src.live.client import run
        arguments = list(sys.argv[1:])
        arguments.remove('--live-client')
        raise SystemExit(run(arguments))
    elif '--check-package' in sys.argv:
        from src.diagnostics.package_check import run_package_check
        raise SystemExit(run_package_check())
    else:
        import ok
        from src.config import config
        from src.controls.interaction import migrate_saved_interaction
        migrate_saved_interaction(config['config_folder'])
        from src.runtime.gpu_ocr import install_gpu_ocr
        install_gpu_ocr()  # Before TaskExecutor starts its background OCR initialization.
        application = ok.OK(config)
        try:
            application.start()
        finally:
            if ok.og.my_app is not None:
                ok.og.my_app.stop()
