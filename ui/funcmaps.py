from utils.io_utils import build_funcmap
from utils.fontformat import FontFormat
from utils.config import pcfg
from utils.textblock_mask import canny_flood, connected_canny_flood, existing_mask
from ui.fontformat_commands import (
    handle_gradient_enabled,
    handle_gradient_start_color,
    handle_gradient_end_color,
    handle_gradient_angle,
    handle_gradient_size
)

# Build base function map
handle_ffmt_change = build_funcmap('ui.fontformat_commands', 
                                     list(FontFormat.params().keys()), 
                                     'ffmt_change_', verbose=False)

# Add gradient handlers
handle_ffmt_change.update({
    'gradient_enabled': handle_gradient_enabled,
    'gradient_start_color': handle_gradient_start_color,
    'gradient_end_color': handle_gradient_end_color,
    'gradient_angle': handle_gradient_angle,
    'gradient_size': handle_gradient_size
})

def get_maskseg_method():
    return [canny_flood, connected_canny_flood, existing_mask][pcfg.drawpanel.rectool_method]