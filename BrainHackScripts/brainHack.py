import mne
import os
import pycnbi.utils.q_common as qc
import numpy as np
from pycnbi.utils import pycnbi_utils as pu
from pycnbi.stream_receiver.stream_receiver import StreamReceiver
from eeg_processing import BrainHackEEGProcessing
from arduino_handler import ArduinoCommHandler
from leds_csv_index import leds_csv_sources

EEG_CH_NAMES = [
    'TRIGGER', 'P3', 'C3', 'F3', 'Fz', 'F4', 'C4', 'P4', 'Cz', 'Pz',
    'Fp1', 'Fp2', 'T3', 'T5', 'O1', 'O2', 'X3', 'X2', 'F7', 'F8', 'X1',
    'A2', 'T6', 'T4'
]

window_max_power = 0
window_min_power = 0
last_max_values = []
last_min_values = []
qnt_max_values = 0
qnt_min_values = 0


def normalize_array(input_array):
    max_value = input_array.max()
    min_value = input_array.min()
    range_value = max_value - min_value
    return (input_array - min_value) / range_value

def normalize_array_with_min_max(input_array, max_value, min_value):
    # max_value = input_array.max()
    # min_value = input_array.min()
    range_value = max_value - min_value
    return (input_array - min_value) / range_value

if __name__ == '__main__':
    brainhack = BrainHackEEGProcessing(sampling_frequency=300,
                                       eeg_ch_names=EEG_CH_NAMES.copy())
    arduino = ArduinoCommHandler(port_name='/dev/ttyACM0', baudrate=115200)
    arduino.start_communication()
    leds_values = [0] * 191
    leds_values_index_for_test = 0

    mne.set_log_level('ERROR')
    # actually improves performance for multitaper
    os.environ['OMP_NUM_THREADS'] = '1'

    amp_name, amp_serial = pu.search_lsl()
    sr = StreamReceiver(
        window_size=1, buffer_size=1, amp_name=amp_name,
        amp_serial=amp_serial, eeg_only=True
    )
    sfreq = sr.get_sample_rate()
    watchdog = qc.Timer()
    tm = qc.Timer(autoreset=True)
    trg_ch = sr.get_trigger_channel()
    last_ts = 0
    # qc.print_c('Trigger channel: %d' % trg_ch, 'G')

    fmin = 1
    fmax = 47
    psde = mne.decoding.PSDEstimator(
        sfreq=sfreq, fmin=fmin, fmax=fmax, bandwidth=None,
        adaptive=False, low_bias=True, n_jobs=1,
        normalization='length', verbose=None
    )

    while True:
        sr.acquire()
        window, tslist = sr.get_window()  # window = [samples x channels]
        window = window.T  # chanel x samples

        # print event values
        tsnew = np.where(np.array(tslist) > last_ts)[0][0]
        trigger = np.unique(window[trg_ch, tsnew:])

        # if len(trigger) > 0:
            # qc.print_c('Triggers: %s' % np.array(trigger), 'G')

        # print('[%.1f] Receiving data...' % watchdog.sec())

        # ADD YOUR CODE
        unused_channels = ['TRIGGER', 'X1', 'X2', 'X3', 'A2']
        brainhack.eeg_ch_names = EEG_CH_NAMES.copy()
        brainhack.window_signal = window
        brainhack.remove_unused_channels(unused_channels)
        brainhack.convert_to_mne_obj()
        brainhack.filter_signal(start_freq=fmin, stop_freq=fmax)
        brainhack.convert_mne_back_to_np_array()
        brainhack.multiply_inverse_solution()

        window = brainhack.sources # shape 5004x300
        window = window[leds_csv_sources, :] # Shape 191x300

        # Computing the power spectrum density using multitapers
        psd = psde.transform(
            window.reshape((1, window.shape[0], window.shape[1]))
        )
        # channels x frequencies
        psd = psd.reshape((psd.shape[1], psd.shape[2]))

        alpha_average_power = psd[:, 8:12].mean(1)
        # beta_average_power = psd[:, 13:40].mean(1)
        print(alpha_average_power.mean())

        last_max_values.append(alpha_average_power.max())
        if len(last_max_values) > 1000:
            last_max_values.pop(0)

        last_min_values.append(alpha_average_power.min())
        if len(last_min_values) > 1000:
            last_min_values.pop(0)

        max = np.mean(last_max_values) + np.std(last_max_values)
        min = np.mean(last_min_values) - np.std(last_min_values)

        print("max: %.4f, min: %.4f -- mean_max: %.4f, mean_min: %.4f" % (
            alpha_average_power.max(), alpha_average_power.min(),
            max, min
        ))

        # alpha_normalized = normalize_array(alpha_average_power) * 255

        # alpha_normalized = normalize_array_with_min_max(
        #     alpha_average_power, max_value=max, min_value=min
        # ) * 255

        alpha_normalized = normalize_array_with_min_max(
            alpha_average_power, max_value=0.015, min_value=0.01
        ) * 255


        alpha_normalized[alpha_normalized>255] = 255
        alpha_normalized[alpha_normalized<0] = 0
        alpha_normalized = alpha_normalized.astype(np.uint8)
        leds_values = list(alpha_normalized)
        # leds_values = [127] * 191
        # leds_values[leds_values_index_for_test] = 255
        # leds_values[leds_values_index_for_test-1] = 255
        # leds_values[leds_values_index_for_test-2] = 127
        # leds_values[leds_values_index_for_test-3] = 0
        # leds_values[leds_values_index_for_test-4] = 0
        # leds_values_index_for_test = leds_values_index_for_test + 1
        # if leds_values_index_for_test >= 191:
            # leds_values_index_for_test = 0
        # leds_values = list(np.random.randint(0, 255, 191))
        arduino.send_led_values(leds_values)

        last_ts = tslist[-1]
        tm.sleep_atleast(0.05)
