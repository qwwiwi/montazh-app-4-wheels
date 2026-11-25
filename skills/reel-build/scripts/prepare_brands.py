"""Build a brand cue manifest for the frozen cut using the local graphics catalog."""
import argparse
import json
from pathlib import Path
from brands import prepare_brands

if __name__ == '__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('words',type=Path)
    cli.add_argument('--catalog',type=Path,required=True)
    cli.add_argument('--assets',type=Path,required=True)
    cli.add_argument('--candidates',type=Path,help='Optional JSON array of {first,last} word indices')
    cli.add_argument('-o','--output',type=Path,required=True)
    args=cli.parse_args()
    hints=json.loads(args.candidates.read_text()) if args.candidates else []
    args.assets.mkdir(parents=True,exist_ok=True)
    report=prepare_brands(args.words,args.catalog,args.assets,candidates=hints)
    args.output.write_text(json.dumps(report,indent=2,ensure_ascii=False))
