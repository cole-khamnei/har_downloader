import argparse
import os
import re
import urllib.request
import subprocess
import shutil
import sys

import ffmpeg

from typing import List, Optional, Tuple
from tqdm import tqdm


"""
https://www.reddit.com/r/YouShouldKnow/comments/296efo/ysk_how_to_download_any_videos_from_any_website/
"""

def safe_user_choice(prompt: str, *options: tuple) -> str:
    """"""
    attempt_counter = 0
    options = tuple(option.lower() for option in options)

    for attempt_counter in range(1, 3):
        choice = input(f"{prompt} [{'/'.join(options)}]: ").lower()
        if choice in options:
            return choice
        print(f"Invalid choice ({choice}). Options are {options}\n")

    assert False, "Too many invalid choices. Please rerun program\n"


def safe_makedirs(dir_path: str):
    """"""
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)


def har_line_filter(line: str) -> bool:
    """"""
    return (".mp4" in line or ".ts" in line or ".aac" in line) and "value" not in line


def get_video_links_from_har(har_file: str) -> list:
    """"""
    with open(har_file, 'r', encoding="utf8") as file:
        har_file = file.read()

    har_file = har_file.split("\n")
    video_links = [line.split('"')[3] for line in har_file if har_line_filter(line)]
    return [link for link in video_links if link.endswith(".ts") or link.endswith(".aac")]


def download_video_fragments(video_links: str, output_path: str) -> Tuple[List[str], List[str]]:
    """"""

    fragment_dir_path = os.path.join(output_path, "fragments")
    output_name = os.path.basename(output_path)

    safe_makedirs(output_path)
    safe_makedirs(fragment_dir_path)
    file_path_i = os.path.join(output_path, "fragments", f"{output_name}_{{number}}.{{extension}}")

    video_file_paths, audio_file_paths = [], []
    for video_link in tqdm(video_links, desc="Downloading video fragments", unit=" videos"):
        number = ("0000000" + re.findall(r'\d+', video_link)[-1])[-5:]
        extension = video_link.split(".")[-1]
        out_path = file_path_i.format(number=number, extension=extension)

        if os.path.exists(out_path) and (out_path in video_file_paths or out_path in audio_file_paths):
            os.remove(out_path)

        if not os.path.exists(out_path):
            urllib.request.urlretrieve(video_link, out_path)

        if out_path in audio_file_paths or out_path in video_file_paths:
            if int(number) > 5 or len(video_links) < 20:
                print("DUPLICATE: ", out_path)
            continue

        if extension == "aac":
            audio_file_paths.append(out_path)
        else:
            video_file_paths.append(out_path)

    return audio_file_paths, video_file_paths


def integrated_audio_concat(output_path: str, video_file_paths: list, video_path: Optional[str] = None) -> None:
    """"""

    file_list_path = f"{output_path}/files.txt"
    with open(file_list_path, 'w') as file:
        for path in video_file_paths:
            path = "\\".join(path.split('\\')[1:])
            file.write(f"file '{path}'\n")
            # break

    if not video_path:
        output_name = os.path.basename(output_path)
        video_path = f"{output_path}/{output_name}.mp4"

    subprocess.call(f"ffmpeg -safe 0 -hide_banner -loglevel error -f concat -i {file_list_path} -c copy {video_path}")
    return video_path


def separate_audio_concat(output_path: str, video_file_paths: list, audio_file_paths: list) -> None:
    """"""
    n_audio, n_video = len(video_file_paths), len(audio_file_paths)
    assert n_audio == n_video, f"number of audio ({n_audio}) and video ({n_video}) files is different."

    temp_dir_path = os.path.join(output_path, "temp")
    safe_makedirs(temp_dir_path)
    pbar = tqdm(zip(audio_file_paths, video_file_paths), total=n_audio,
                desc="concatenating fragments", unit="fragment")

    mp4_fragment_paths = []
    for audio_file, video_file in pbar:
        temp_fragment_path = audio_file.replace(".aac", ".mp4").replace("fragments", "temp")
        command = f"ffmpeg -i {video_file} -i {audio_file} -hide_banner -loglevel error "
        command += f" -map 0:V:0 -map 1:a:0 -c copy -f mp4 -movflags +faststart {temp_fragment_path}"
        subprocess.call(command)
        mp4_fragment_paths.append(temp_fragment_path)

    output_name = os.path.basename(output_path)
    video_path = os.path.join(output_path, f"{output_name}.mp4")
    integrated_audio_concat(output_path, mp4_fragment_paths, video_path=video_path)

    shutil.rmtree(temp_dir_path)
    return video_path


def fragment_concat(output_path: str, video_file_paths: List[str], audio_file_paths: List[str]):
    """"""
    if len(audio_file_paths) == 0:
        video_path = integrated_audio_concat(output_path, video_file_paths)
    else:
        video_path = separate_audio_concat(output_path, video_file_paths, audio_file_paths)


    video_size = os.path.getsize(video_path)
    if video_size < 10_000:
        print("Video is {video_size:,}B, this is low. Please manually check to see if video correctly concatenated.")
        return

    os.remove(os.path.join(output_path, "files.txt"))
    shutil.rmtree(os.path.join(output_path, "fragments"))



def get_inputs():
    """"""
    parser = argparse.ArgumentParser(description='Download video using .har file')
    parser.add_argument('--har', dest='har_path', action='store', help="path to .har file", required=True)
    parser.add_argument('--output', dest='output', action='store', default="",
                        help="output name")
    args = parser.parse_args()

    assert os.path.exists(args.har_path), f"{args.har_path} not found."
    assert not any(char in args.output for char in ".,=+()?'|*&^%$#@!`"), f"invalid characters in {args.output}"

    if args.output == "":
        output_path = os.path.basename(args.har_path).rstrip(".har")
    else:
        output_path = args.output

    output_name = os.path.basename(output_path)
    video_path = os.path.join(output_path, f"{output_name}.mp4")
    if os.path.exists(video_path):
        choice = safe_user_choice(f"'{video_path}' already exists. Overwrite?", "y", "n")
        if choice != "y":
            print("Overwrite not chosen. Ending script.")
            sys.exit()
        os.remove(video_path)

    return args.har_path, output_path


def main():
    """"""
    har_path, output_path = get_inputs()

    print(f"Retrieving {os.path.basename(output_path)}:")
    video_links = get_video_links_from_har(har_path)
    audio_file_paths, video_file_paths = download_video_fragments(video_links, output_path)
    fragment_concat(output_path, video_file_paths, audio_file_paths)


if __name__ == '__main__':
    main()
