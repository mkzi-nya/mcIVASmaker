import os
import time
from multiprocessing.pool import ThreadPool, Pool
from multiprocessing import Queue, Manager
from typing import Union, Callable, Optional, Any, Tuple
import queue

import src.ui_manager.PySimpleGUI as sg

from src.logic.image_logic.image_manager import manipulate_image
from src.logic.vid_logic import ffmpeg_manager
from src.path_manager.pather import resource_path
import logging

logger = logging.getLogger(__name__)

assets_path = resource_path(f"./assets/cache/")

# The cache folders
vid_cache_folder_jpg = os.path.normpath(os.path.join(assets_path, "./img_cache_jpg/"))
vid_cache_folder_png = os.path.normpath(os.path.join(assets_path, "./img_cache_png/"))
vid_cache_folder_m4a = os.path.normpath(os.path.join(assets_path, "./audio_cache/"))

vid_processed_folder = os.path.normpath(os.path.join(assets_path, "./img_process_cache/"))

# Create the paths if they don't exist (Git does not recognize empty folders)
if not os.path.exists(vid_cache_folder_jpg):
    os.makedirs(vid_cache_folder_jpg)

if not os.path.exists(vid_cache_folder_png):
    os.makedirs(vid_cache_folder_png)

if not os.path.exists(vid_cache_folder_m4a):
    os.makedirs(vid_cache_folder_m4a)

if not os.path.exists(vid_processed_folder):
    os.makedirs(vid_processed_folder)

THREAD_KEY = '-Vid_Thread-'

ProgressEvent = Tuple[str, Any]
ProgressCallback = Optional[Callable[[ProgressEvent], None]]


def vid_manager(
    window: Union[sg.Window, None],
    filepath: str,
    output: str,
    manipulation: str,
    scale: Union[str, float, int],
    details: dict,
    progress_cb: ProgressCallback = None
):
    """Video pipeline manager. Works for both GUI (window!=None) and CLI (progress_cb!=None)."""

    # Unified event dispatcher (GUI -> write_event_value, CLI -> callback)
    def emit(ev: str, payload: Any = None):
        if progress_cb is not None and window is None:
            progress_cb((ev, payload))
        elif window is not None:
            window.write_event_value((THREAD_KEY, ev), payload)

    # Cleaning cache folders, incase a previous run failed to do so
    cleanup_folders()
    logger.info("Cleaned Previous Cache")
    logger.debug("Video Details:")
    logger.debug(f"FilePath: {filepath}")
    logger.debug(f"Output Path: {output}")
    logger.debug(f"Manupilations: {manipulation}")
    logger.debug(f"Scale: {scale}")
    logger.debug(f"Details: {details}")

    # Instantiating the process/thread related objects
    process_count = details['process_count']
    process_pool = Pool(processes=process_count)
    ff_pool = ThreadPool(processes=2)
    manager = Manager()
    event_queue = manager.Queue()

    frame_count = ffmpeg_manager.get_frame_count(filepath, details['frame_rate'])
    # Close enough frame count
    emit('-Image_Count-', frame_count)

    # Selecting the correct cache folder
    cache_folder = vid_cache_folder_png if details['quality'] else vid_cache_folder_jpg

    # Running the encoder?(In another thread)
    ff_pool.apply_async(
        ffmpeg_manager.vid_to_img,
        (filepath, details['frame_rate'], cache_folder),
        callback=(lambda x: print(f"[ffmpeg extract] exit={x}")) if (progress_cb and window is None) else None
    )
    ff_pool.apply_async(ffmpeg_manager.vid_to_audio, (filepath,))
    ff_pool.close()

    # Starting the image conversion, till at least 95% the images are there
    current_image = 0
    image_processes = []
    img_count = 0
    while True:
        # Checking the number of files that have been outputted by ffmpeg
        files = os.listdir(cache_folder)
        file_count = len(files)
        if file_count >= (frame_count * 0.95):
            break
        # Updating the progress meter (0..1 for extract phase)
        emit('-Img_Conversion-', file_count / frame_count)

        # Start processing images while ffmpeg is generating them
        if file_count > current_image:
            img_file_path = os.path.join(cache_folder, files[current_image])
            # Remove the first 4 and last 4 characters, to get just the number
            file_number = os.path.split(img_file_path)[1][4:-4]
            processed_path = os.path.join(vid_processed_folder, file_number + ".png")
            image_processes.append(process_pool.apply_async(
                manage_single_image,
                (event_queue, img_file_path, processed_path, manipulation, scale, details)
            ))
            current_image += 1

        # Item count checking frequency
        time.sleep(0.1)
    ff_pool.join()
    logger.info("Converted Video to images")

    # Flush completed early processes
    for process in image_processes:
        process.wait()
        emit('-Image_Done-', None)
        img_count += 1

    # Update images done
    emit('-Set_Images_Done-', img_count)

    # Extract done
    emit('-Img_Conversion-', 1)
    logger.debug("Completed partial processing")

    # Getting the correct item count and finding which files we have to process now
    files = os.listdir(cache_folder)
    file_count = len(files)
    completed_files = os.listdir(vid_processed_folder)
    for completed_file in completed_files:
        file_no = completed_file.replace(".png", "")
        name_of_file = "file" + file_no + (".jpg" if cache_folder == vid_cache_folder_jpg else ".png")
        if name_of_file in files:
            files.remove(name_of_file)

    emit('-Image_Count-', file_count)

    # Processing the rest of the images
    for unprocessed_file in files:
        img_file_path = os.path.join(cache_folder, unprocessed_file)
        file_number = os.path.split(img_file_path)[1][4:-4]
        processed_path = os.path.join(vid_processed_folder, file_number + ".png")
        image_processes.append(process_pool.apply_async(
            manage_single_image,
            (event_queue, img_file_path, processed_path, manipulation, scale, details)
        ))
        current_image += 1

    process_pool.close()
    iter_count = 0
    while True:
        try:
            data = event_queue.get(timeout=0.2)  # 不阻塞太久，0.2s 轮询
            if data[0] == "-Single_Frame-":
                if window is not None:
                    window['-Single_Frame-'](data[1])
                emit('-Single_Frame-', data[1])
            elif data[0] == "-Image_Done-":
                # 可选：这里其实我们上面已经在 wait 后 emit 过一次，
                # 如果你希望更顺滑，也可以在这里对 CLI 做一次进度+1
                emit('-Image_Done-', None)
        except queue.Empty:
            pass

        if all(proc.ready() for proc in image_processes):
            break

        iter_count += 1
        if window is not None and iter_count % 10 == 0:
            processed_file_count = len(os.listdir(vid_processed_folder))
            progress = processed_file_count / file_count * 100
            window['-Number_Of_Frames-'](progress)
            window['-Number_Of_Frames_Text-'](f"{processed_file_count}/{file_count}")

        if any([not proc.successful() for proc in image_processes if proc.ready()]):
            logger.error("ERROR!")
            proc_list = [not proc.successful() for proc in image_processes if proc.ready()]
            indices = [i for i, x in enumerate(proc_list) if x]
            for index in indices:
                logger.error(image_processes[index].get())

    process_pool.join()

    # If the processing was very fast, make sure we emit remaining done events
    # GUI: just set the single-frame meter to 100
    if window is not None:
        window
    # Emit missing '-Image_Done-' to match frame_count
    for _ in range(img_count, frame_count):
        emit('-Image_Done-', None)

    emit('-Img_Conversion-', 1.4)
    logger.info("Completed Image Processing")

    # Creating the ffmpeg run command
    if len(os.listdir(vid_cache_folder_m4a)) > 0:
        re_options = (
            f"-i {os.path.join(vid_cache_folder_m4a, 'audio.m4a')} "
            f"-r {details['frame_rate']} "
            f"-i {os.path.join(vid_processed_folder, '%01d.png')} "
            f"-crf 20 -pix_fmt yuv420p {output}"
        )
    else:
        re_options = (
            f"-r {details['frame_rate']} -i {os.path.join(vid_processed_folder, '%01d.png')} "
            f"-crf 20 -pix_fmt yuv420p {output}"
        )
    logger.debug("The ffmpeg converted join command: " + re_options)
    ffmpeg_manager.ffmpeg_runner(re_options)

    emit('-Img_Conversion-', 1.8)
    logger.info("Video Created")

    # Cleaning up the cache folders
    cleanup_folders()
    logger.info("Cleaning Cache")

    emit('-Img_Conversion-', 2)
    logger.info("Video Conversion Completed!")


# Cleans up cache
def cleanup_folders():
    cache_png_files = os.listdir(vid_cache_folder_png)
    for file in cache_png_files:
        os.remove(os.path.join(vid_cache_folder_png, file))

    cache_jpg_files = os.listdir(vid_cache_folder_jpg)
    for file in cache_jpg_files:
        os.remove(os.path.join(vid_cache_folder_jpg, file))

    cache_processed_files = os.listdir(vid_processed_folder)
    for file in cache_processed_files:
        os.remove(os.path.join(vid_processed_folder, file))

    audio_processed_files = os.listdir(vid_cache_folder_m4a)
    for file in audio_processed_files:
        os.remove(os.path.join(vid_cache_folder_m4a, file))


# Running this for every single frame
def manage_single_image(
    event_queue: Queue,
    filename: str,
    output: str,
    manipulation: str,
    scale: Union[str, float, int],
    details: dict
):
    manipulation = manipulation.replace("Video", "Image")
    iteration = 0
    image_size = 1
    updates = 30
    # Using the same "image to blocks" conversion as in the image tab
    for values in manipulate_image(filename, output, manipulation, None, scale, details):
        if iteration == 0:
            image_size = values
        iteration += 1
        # Updating the progress every certain amount of iterations
        if image_size and iteration % max(1, round(image_size / updates)) == 0:
            if isinstance(values, str):
                pass
            else:
                event_queue.put(['-Single_Frame-', values / image_size * 100])
    event_queue.put(['-Image_Done-', output])
