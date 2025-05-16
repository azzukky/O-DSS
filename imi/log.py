def log_debug(s):
    print(f'[DEBUG] {s}')
    #self.logger.debug(s) if self is not None else print(f'[DEBUG] {s}')

def log_info(s):
    print(f'[INFO] {s}')
    #self.logger.info(s) if self is not None else print(f'[INFO] {s}')

def log_error(s):
    print(f'[ERROR] {s}')
    #self.logger.error(s) if self is not None else print(f'[ERROR] {s}')

def log_warning(s):
    print(f'[WARNING] {s}')
    #self.logger.warning(s) if self is not None else print(f'[WARNING] {s}')