from __future__ import absolute_import

from __future__ import print_function

import os
import sys
import json
import numpy as np
import time
import copy
import argparse
import copy
import json
import os
import numpy as np
from pub_tracker import PubTracker as Tracker
from nuscenes import NuScenes
import json
import time
from nuscenes.utils import splits

from warnings import simplefilter
simplefilter(action="ignore",category=FutureWarning)


def parse_args():
    parser = argparse.ArgumentParser(description="Tracking Evaluation")
    parser.add_argument(
        "--work_dir", help="the dir to save logs and tracking results", default='./work_dirs/')
    parser.add_argument(
        "--checkpoint", help="the dir to checkpoint which the model read from", default='./work_dirs/results_nusc.json'
    )
    parser.add_argument("--hungarian", action='store_true')
    parser.add_argument("--data_root", type=str, default='./data/nuscenes/')
    parser.add_argument("--version", type=str, default='v1.0-trainval')
    parser.add_argument("--max_age", type=int, default=3)
    parser.add_argument("--score_threshold", type=int, default=0.25)
    args = parser.parse_args()

    print(args)
    return args


def save_first_frame(args):
    nusc = NuScenes(version=args.version,
                    dataroot=args.data_root, verbose=True)
    print("nusc version: ", args.version)
    if args.version == 'v1.0-trainval':
        scenes = splits.val
    elif args.version == 'v1.0-test':
        scenes = splits.test
    elif args.version == 'v1.0-mini':
        scenes = splits.mini_val

    frames = []
    for sample in nusc.sample:
        scene_name = nusc.get("scene", sample['scene_token'])['name']
        if scene_name not in scenes:
            continue

        timestamp = sample["timestamp"] * 1e-6
        token = sample["token"]
        frame = {}
        frame['token'] = token
        frame['timestamp'] = timestamp

        # start of a sequence
        if sample['prev'] == '':
            frame['first'] = True
        else:
            frame['first'] = False
        frames.append(frame)

    del nusc

    res_dir = os.path.join(args.work_dir)
    if not os.path.exists(res_dir):
        os.makedirs(res_dir)

    with open(os.path.join(args.work_dir, 'frames_meta.json'), "w") as f:
        json.dump({'frames': frames}, f)


def main(args):
    print('Deploy OK')

    tracker = Tracker(max_age=args.max_age, hungarian=args.hungarian)

    with open(args.checkpoint, 'rb') as f:
        predictions = json.load(f)['results']

    with open(os.path.join(args.work_dir, 'frames_meta.json'), 'rb') as f:
        frames = json.load(f)['frames']

    nusc_annos = {
        "results": {},
        "meta": None,
    }
    size = len(frames)

    print("Begin Tracking\n")
    start = time.time()
    for i in range(size):
        token = frames[i]['token']

        # reset tracking after one video sequence
        if frames[i]['first']:
            # use this for sanity check to ensure your token order is correct
            # print("reset ", i)
            tracker.reset()
            last_time_stamp = frames[i]['timestamp']

        time_lag = (frames[i]['timestamp'] - last_time_stamp)
        last_time_stamp = frames[i]['timestamp']

        preds = predictions[token]

        outputs = tracker.step_centertrack(
            preds, time_lag, args.score_threshold)
        annos = []

        for item in outputs:
            if item['active'] == 0:
                continue
            nusc_anno = {
                "sample_token": token,
                "translation": item['translation'],
                "size": item['size'],
                "rotation": item['rotation'],
                "velocity": item['velocity'],
                "tracking_id": str(item['tracking_id']),
                "tracking_name": item['detection_name'],
                "tracking_score": item['detection_score'],
            }
            annos.append(nusc_anno)
        nusc_annos["results"].update({token: annos})

    end = time.time()

    second = (end-start)

    speed = size / second
    print("The speed is {} FPS".format(speed))

    nusc_annos["meta"] = {
        "use_camera": False,
        "use_lidar": True,
        "use_radar": False,
        "use_map": False,
        "use_external": False,
    }

    res_dir = os.path.join(args.work_dir)
    if not os.path.exists(res_dir):
        os.makedirs(res_dir)

    with open(os.path.join(args.work_dir, 'tracking_result.json'), "w") as f:
        json.dump(nusc_annos, f)
    return speed


def eval_tracking(args):
    if args.version in ['v1.0-mini', 'v1.0-trainval']:
        eval(os.path.join(args.work_dir, 'tracking_result.json'),
             args.version,
             args.work_dir,
             args.data_root
             )
    else:
        print('Only support for v1.0-mini or v1.0-trainval')


def eval(res_path, version="v1.0-trainval", output_dir=None, root_path=None):
    from nuscenes.eval.tracking.evaluate import TrackingEval
    from nuscenes.eval.common.config import config_factory as track_configs
    eval_set_map = {
        'v1.0-mini': 'mini_val',
        'v1.0-trainval': 'val',
    }

    cfg = track_configs("tracking_nips_2019")
    nusc_eval = TrackingEval(
        config=cfg,
        result_path=res_path,
        eval_set=eval_set_map[version],
        output_dir=output_dir,
        verbose=True,
        nusc_version=version,
        nusc_dataroot=root_path,
    )
    metrics_summary = nusc_eval.main()


def test_time():
    speeds = []
    for i in range(3):
        speeds.append(main())

    print("Speed is {} FPS".format(max(speeds)))


if __name__ == '__main__':
    args = parse_args()
    save_first_frame(args)
    main(args)
    eval_tracking(args)
