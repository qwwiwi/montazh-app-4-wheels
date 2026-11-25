"""Exercise the native component builder before paying for a storyboard review."""
import json


class ComponentError(ValueError):
    pass


def validate(plan, builders):
    from scenes_hc import HC_EXAMPLES
    errors=[]
    for sc in plan.scenes:
        if sc.kind not in HC_EXAMPLES:
            continue
        try:
            builders.build_scene(sc,plan.shots[sc.shot].type=='visual')
        except (KeyError,TypeError,IndexError,ValueError,ArithmeticError) as exc:
            specimen=HC_EXAMPLES[sc.kind]
            note=f'{type(exc).__name__} {exc}'
            if isinstance(exc,KeyError) and exc.args[0] in specimen:
                field=exc.args[0]
                note+=f'; required field {field}: '+json.dumps(specimen[field],ensure_ascii=False)
            errors.append(f'shot {sc.shot} {sc.kind} {sc.start:.3f}-{sc.end:.3f}: {note}. Use exact in-shot word anchors and factual scene copy.')
    if errors:
        raise ComponentError('\n'.join(errors))
