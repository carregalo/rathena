"""NPC windows: answering them (menus, inputs, shops, storage), describing them, remembering what NPCs do."""
import json
import re

from gamedata import to_game_text
from luaengine import short_name

def _item_list(text):
    """[{"item": name, "amount": n}, ...] from JSON, or None."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    out = []
    for e in data:
        if isinstance(e, dict) and str(e.get("item", "")).strip():
            try:
                out.append((str(e["item"]).strip().lower(), max(1, int(e.get("amount", 1)))))
            except (TypeError, ValueError):
                return None
    return out


def answer_npc(client, body, reply):
    """Applies her answer to the NPC window that is open (menu, number, text, shop, storage).
    Returns what happened, in words she understands."""
    w = client.world
    wait = w.npc_wait
    if not wait:
        return "nenhum NPC esperando resposta"
    r = reply.strip()
    names = body.item_names
    if not r or r.lower() in ("sair", "cancelar", "fechar", "nada"):
        client.close_npc()
        return f"voce saiu da conversa com {short_name(wait['name'])}"
    kind = wait["kind"]
    if kind == "menu":
        options = wait["options"]
        number = int(r) if r.isdigit() else next(
            (i + 1 for i, o in enumerate(options) if o and o.lower() == r.lower()), None) or next(
            (i + 1 for i, o in enumerate(options) if o and r.lower() in o.lower()), None)
        if not number or not 1 <= number <= len(options) or not options[number - 1]:
            return f"'{r}' nao e uma das opcoes; responda com o numero de uma opcao"
        client.answer_menu(number)
        return f"voce escolheu: {options[number - 1]}"
    if kind == "number":
        digits = re.sub(r"[^0-9-]", "", r)
        if not digits.lstrip("-").isdigit():
            return "o NPC pediu um numero"
        client.answer_number(int(digits))
        return f"voce respondeu {int(digits)}"
    if kind == "text":
        client.answer_text(to_game_text(r, 70))
        return f"voce respondeu '{to_game_text(r, 70)}'"
    if kind == "deal":
        sell = r.lower().startswith(("vend", "sell"))
        if not sell and not r.lower().startswith(("compr", "buy")):
            return "responda comprar, vender ou sair"
        client.deal(sell)
        return "voce quis " + ("vender" if sell else "comprar")
    if kind in ("buy", "sell"):
        wanted = _item_list(r)
        if not wanted:
            return 'responda uma lista JSON, ex.: [{"item": "Red Potion", "amount": 3}], ou sair'
        chosen, total = [], 0
        for name, amount in wanted:
            if kind == "buy":
                match = next(((i, price) for i, price in wait["items"] if names.get(i, "").lower() == name), None)
                if not match:
                    return f"{name} nao esta a venda aqui"
                chosen.append((match[0], amount))
                total += match[1] * amount
            else:
                sellable = {index for index, _ in wait["items"]}
                item = next((i for i in w.inventory.values()
                             if names.get(i.item_id, "").lower() == name and i.index in sellable), None)
                if not item:
                    return f"voce nao tem {name} que este NPC compre"
                chosen.append((item.index, min(amount, item.amount)))
        if kind == "buy" and total > w.zeny:
            return f"custaria {total} zeny e voce tem {w.zeny}"
        w.npc_wait = None
        (client.buy if kind == "buy" else client.sell)(chosen)
        return ("voce pediu para comprar " if kind == "buy" else "voce pediu para vender ") + \
            ", ".join(f"{names.get(i, i) if kind == 'buy' else names.get(w.inventory[i].item_id, i)} x{a}"
                      for i, a in chosen)
    if kind == "storage":
        try:
            data = json.loads(r)
        except ValueError:
            return 'responda {"guardar": [{"item": ..., "amount": ...}], "retirar": [...]} ou fechar'
        done = []
        for name, amount in _item_list(json.dumps(data.get("guardar", []))) or []:
            item = next((i for i in w.inventory.values() if names.get(i.item_id, "").lower() == name and not i.worn), None)
            if item:
                client.storage_put(item.index, min(amount, item.amount))
                done.append(f"guardou {names.get(item.item_id)} x{min(amount, item.amount)}")
        for name, amount in _item_list(json.dumps(data.get("retirar", []))) or []:
            item = next((i for i in w.storage.values() if names.get(i.item_id, "").lower() == name), None)
            if item:
                client.storage_get(item.index, min(amount, item.amount))
                done.append(f"retirou {names.get(item.item_id)} x{min(amount, item.amount)}")
        return "; ".join(done) or "nada foi guardado nem retirado (itens nao encontrados)"
    return "nada a fazer"


def note_npc_service(mind, w, item_names):
    """Records what an NPC turned out to offer, from the window it opened."""
    wait = w.npc_wait
    if not wait:
        return
    name, kind = wait["name"], wait["kind"]
    if kind == "menu":
        mind.npc_does(name, "oferece: " + " / ".join(o for o in wait["options"] if o)[:180])
    elif kind == "deal":
        mind.npc_does(name, "tem uma loja (compra e vende)")
    elif kind == "buy":
        mind.npc_does(name, "vende: " + ", ".join(item_names.get(i, str(i)) for i, _ in wait["items"][:8]))
    elif kind == "storage":
        mind.npc_does(name, "abre o seu armazem")
    elif kind in ("number", "text"):
        mind.npc_does(name, f"pede que voce digite um {'numero' if kind == 'number' else 'texto'}")


def describe_wait(w, item_names):
    """The open NPC window and how to answer it, for the prompt."""
    wait = w.npc_wait
    name = short_name(wait["name"])
    kind = wait["kind"]
    if kind == "menu":
        opts = [f"{i + 1}) {o}" for i, o in enumerate(wait["options"]) if o]
        return [f"{name} espera voce escolher uma opcao (responda em npc_reply com o numero; vazio sai):", *opts]
    if kind == "number":
        return [f"{name} pediu que voce digite um numero (npc_reply; vazio sai)."]
    if kind == "text":
        return [f"{name} pediu que voce escreva algo (npc_reply; vazio sai)."]
    if kind == "deal":
        return [f"{name} abriu uma loja: responda comprar, vender ou sair em npc_reply."]
    if kind == "buy":
        goods = ", ".join(f"{item_names.get(i, f'item {i}')} ({price} z)" for i, price in wait["items"][:40])
        return [f"{name} vende (preco por unidade): {goods}. Voce tem {w.zeny} zeny.",
                'Para comprar, npc_reply = [{"item": "nome", "amount": n}, ...]; vazio sai.']
    if kind == "sell":
        sellable = {index: over for index, over in wait["items"]}
        goods = ", ".join(f"{item_names.get(i.item_id, i.item_id)} x{i.amount} ({sellable[i.index]} z cada)"
                          for i in w.inventory.values() if i.index in sellable)
        return [f"{name} compra de voce: {goods or 'nada do que voce tem'}.",
                'Para vender, npc_reply = [{"item": "nome", "amount": n}, ...]; vazio sai.']
    if kind == "storage":
        stored = ", ".join(f"{item_names.get(i.item_id, i.item_id)} x{i.amount}" for i in w.storage.values()) or "vazio"
        return [f"O armazem esta aberto. Guardado: {stored}.",
                'npc_reply = {"guardar": [{"item": "nome", "amount": n}], "retirar": [...]} ; "fechar" fecha.']
    return []
