#! /usr/bin/python

# (C) 2017 by folkert@vanheusden.com
# released under AGPL v3.0

import chess
import chess.pgn
import collections
from psq import psq, psq_individual
from tt import tt_inc_age, tt_store, tt_lookup, tt_get_pv
from log import l
import math
import operator
import sys
import threading
import time
import traceback

with_qs = True

stats_node_count = 0
stats_tt_checks = stats_tt_hits = 0
stats_avg_bco_index_cnt = stats_avg_bco_index = 0

infinite = 131072
checkmate = 10000

pmaterial_table = [ 0 ] * (6 + 1)
pmaterial_table[chess.PAWN] = 100
pmaterial_table[chess.KNIGHT] = 325
pmaterial_table[chess.BISHOP] = 325
pmaterial_table[chess.ROOK] = 500
pmaterial_table[chess.QUEEN] = 975
pmaterial_table[chess.KING] = 10000

to_flag = None

def set_to_flag(to_flag):
    to_flag.set()
    l("time is up");

def get_stats():
    global stats_avg_bco_index, stats_node_count, stats_tt_hits, stats_tt_checks

    return { 'stats_node_count' : stats_node_count,
        'stats_tt_hits' : stats_tt_hits,
        'stats_tt_checks' : stats_tt_checks,
        'stats_avg_bco_index_cnt' : stats_avg_bco_index_cnt,
        'stats_avg_bco_index' : stats_avg_bco_index
        }

def reset_stats():
    global stats_avg_bco_index_cnt, stats_avg_bco_index, stats_node_count, stats_tt_hits, stats_tt_checks

    stats_avg_bco_index_cnt = stats_avg_bco_index = stats_node_count = stats_tt_checks = stats_tt_hits = 0

def material(pm):
    return sum((1 if pm[p].color else -1) * pmaterial_table[pm[p].piece_type] for p in pm)

def mobility(board):
    if board.turn:
        white_n = board.move_count()

        board.push(chess.Move.null())
        black_n = board.move_count()
        board.pop()

    else:
        black_n = board.move_count()

        board.push(chess.Move.null())
        white_n = board.move_count()
        board.pop()

    return white_n - black_n

def pm_to_filemap(piece_map):
    files = [ 0 ] * (8 * 7 * 2)

    for p, piece in piece_map.items():
        files[piece.color * 8 * 7 + piece.piece_type * 8 + (p & 7)] += 1

    return files

def count_double_pawns(file_map):
    n = 0

    for i in range(0, 8):
        if file_map[chess.WHITE * 8 * 7 + chess.PAWN * 8 + i] >= 2:
            n += file_map[chess.WHITE * 8 * 7 + chess.PAWN * 8 + i] - 1

        if file_map[chess.BLACK * 8 * 7 + chess.PAWN * 8 + i] >= 2:
            n -= file_map[chess.BLACK * 8 * 7 + chess.PAWN * 8 + i] - 1

    return n

def count_rooks_on_open_file(file_map):
    n = 0

    for i in range(0, 8):
        if file_map[chess.WHITE * 8 * 7 + chess.PAWN * 8 + i] == 0 and file_map[chess.WHITE * 8 * 7 + chess.ROOK * 8 + i] > 0:
            n += 1

        if file_map[chess.BLACK * 8 * 7 + chess.PAWN * 8 + i] == 0 and file_map[chess.BLACK * 8 * 7 + chess.ROOK * 8 + i] > 0:
            n -= 1

    return n

def passed_pawn(pm, is_end_game):
    whiteYmax = [ -1 ] * 8
    blackYmin = [ 8 ] * 8

    for key, p in pm.items():
        if p.piece_type != chess.PAWN:
            continue

        x = key & 7
        y = key >> 3

        if p.color == chess.WHITE:
            whiteYmax[x] = max(whiteYmax[x], y)
        else:
            blackYmin[x] = min(blackYmin[x], y)

    scores = [ [ 0, 5, 20, 30, 40, 50, 80, 0 ], [ 0, 5, 20, 40, 70, 120, 200, 0 ] ]

    score = 0

    for key, p in pm.items():
        if p.piece_type != chess.PAWN:
            continue

        x = key & 7
        y = key >> 3

        if p.color == chess.WHITE:
            left = (x > 0 and (blackYmin[x - 1] <= y or blackYmin[x - 1] == 8)) or x == 0;
            front = blackYmin[x] < y or blackYmin[x] == 8;
            right = (x < 7 and (blackYmin[x + 1] <= y or blackYmin[x + 1] == 8)) or x == 7;

            if left and front and right:
                score += scores[is_end_game][y];

        else:
            left = (x > 0 and (whiteYmax[x - 1] >= y or whiteYmax[x - 1] == -1)) or x == 0;
            front = whiteYmax[x] > y or whiteYmax[x] == -1;
            right = (x < 7 and (whiteYmax[x + 1] >= y or whiteYmax[x + 1] == -1)) or x == 7;

            if left and front and right:
                score -= scores[is_end_game][7 - y];

    return score

def evaluate(board):
    pm = board.piece_map()

    score = material(pm)

    score += psq(pm) / 4

#    score += mobility(board) * 10

    score += passed_pawn(pm, False) # FIXME

#    pfm = pm_to_filemap(pm)

#    score += count_double_pawns(pfm)

#    score += count_rooks_on_open_file(pfm)

    if board.turn:
        return score

    return -score

class pc_move(object):
    __slots__ = ['score', 'move']

    def __init__(self, score, move):
        self.score = score
        self.move = move

def victim_type_for_move(board, m):
    if board.is_en_passant(m):
        return chess.PAWN

    return board.piece_type_at(m.to_square)

def pc_to_list(board, moves_first):
    out = []

    for m in board.get_move_list():
        c = pc_move(0, m)

        if m.promotion:
            c.score += pmaterial_table[m.promotion] << 18

        if board.is_capture(m): # FIXME
            victim_type = victim_type_for_move(board, m)
            c.score += pmaterial_table[victim_type] << 18

            me = board.piece_at(m.from_square)
            c.score += (pmaterial_table[chess.QUEEN] - pmaterial_table[me.piece_type]) << 8

        # -20 elo: 
        #else:
        #	me = board.piece_at(m.from_square)
        #	score += psq_individual(m.to_square, me) - psq_individual(m.from_square, me)

        out.append(c)

    for i in range(0, len(moves_first)):
        for m in out:
            if m.move == moves_first[i]:
                m.score = infinite - i
                break

    out.sort(key=operator.attrgetter('score'), reverse = True)

    return out

def blind(board, m):
    victim_type = victim_type_for_move(board, m)
    victim_eval = pmaterial_table[victim_type]

    me_type = board.piece_type_at(m.from_square)
    me_eval = pmaterial_table[me_type]

    return victim_eval < me_eval and board.attackers(not board.turn, m.to_square)

def is_draw(board):
    if board.halfmove_clock >= 100:
        return True

    # FIXME enough material counts

    return False

def qs(board, alpha, beta):
    global to_flag
    if to_flag.is_set():
        return -infinite

    global stats_node_count
    stats_node_count += 1

    if board.is_checkmate():
        return -checkmate

    if is_draw(board):
        return 0

    best = -infinite

    is_check = board.is_check()
    if not is_check:
        best = evaluate(board)

        if best > alpha:
            alpha = best

            if best >= beta:
                return best

    moves = pc_to_list(board, [])

    move_count = 0
    for m_work in moves:
        m = m_work.move

        if not board.is_legal(m):
            continue

        is_capture_move = board.piece_type_at(m.to_square) != None

        if is_check == False:
            if is_capture_move == False and m.promotion == None:
                continue

            if is_capture_move and blind(board, m):
                continue

        move_count += 1

        board.push(m)

        score = -qs(board, -beta, -alpha)

        board.pop()

        if score > best:
            best = score

            if score > alpha:
                alpha = score

                if score >= beta:
                    global stats_avg_bco_index, stats_avg_bco_index_cnt
                    stats_avg_bco_index += move_count - 1
                    stats_avg_bco_index_cnt += 1
                    break

    if move_count == 0:
        return evaluate(board)

    return best

def tt_lookup_helper(board, alpha, beta, depth):
    tt_hit = tt_lookup(board)
    if not tt_hit:
        return None

    rc = (tt_hit.score, tt_hit.move)

    if tt_hit.depth < depth:
        return [ False, rc ]

    if tt_hit.flags == 'E':
        return [ True, rc ]

    if tt_hit.flags == 'L' and tt_hit.score >= beta:
        return [ True, rc ]

    if tt_hit.flags == 'U' and tt_hit.score <= alpha:
        return [ True, rc ]

    return [ False, rc ]

def search(board, alpha, beta, depth, siblings, max_depth, is_nm):
    global to_flag
    if to_flag.is_set():
        return (-infinite, None)

    if board.is_checkmate():
        return (-checkmate, None)

    if is_draw(board):
        return (0, None)

    if depth == 0:
        if with_qs:
            return (qs(board, alpha, beta), None)

        v = evaluate(board)

        return (-v if board.turn == chess.BLACK else v, None)

    top_of_tree = depth == max_depth

    global stats_node_count
    stats_node_count += 1

    global stats_tt_checks
    stats_tt_checks += 1
    tt_hit = tt_lookup_helper(board, alpha, beta, depth)
    if tt_hit:
        global stats_tt_hits
        stats_tt_hits += 1

        if tt_hit[0]:
            return tt_hit[1]

    alpha_orig = alpha

    best = -infinite
    best_move = None

    ### NULL MOVE ###
    if not board.is_check() and depth >= 3 and not top_of_tree and not is_nm:
        board.push(chess.Move.null())
        nm_result = search(board, -beta, -beta + 1, depth - 3, [], max_depth, True)
        board.pop()

        if -nm_result[0] >= beta:
            return (-nm_result[0], None)
    #################

    moves_first = []
    if tt_hit and tt_hit[1][1]:
        moves_first.append(tt_hit[1][1])

    moves_first += siblings

    moves = pc_to_list(board, moves_first)

    new_siblings = []

    is_check = board.is_check()
    allow_lmr = depth >= 3 and not is_check

    move_count = 0
    for m_work in moves:
        m = m_work.move
        if not board.is_legal(m):
            continue

        move_count += 1

        new_depth = depth - 1

        lmr = False
        if allow_lmr and move_count >= 4 and not board.is_capture(m) and not m.promotion:
            lmr = True
            new_depth -= 1

            if move_count >= 6:
                new_depth -= 1

        board.push(m)

        result = search(board, -beta, -alpha, new_depth, new_siblings, max_depth, False)
        score = -result[0]

        if score > alpha and lmr:
            result = search(board, -beta, -alpha, depth - 1, new_siblings, max_depth, False)
            score = -result[0]

        board.pop()

        if score > best:
            best = score
            best_move = m

            if not m in siblings:
                if len(siblings) == 2:
                    del siblings[-1]

                siblings.insert(0, m)

            if score > alpha:
                alpha = score

                if score >= beta:
                    global stats_avg_bco_index, stats_avg_bco_index_cnt
                    stats_avg_bco_index += move_count - 1
                    stats_avg_bco_index_cnt += 1
                    break

    if move_count == 0:
        if not is_check:
            return (0, None)

        l('ERR')

    if alpha > alpha_orig and not to_flag.is_set():
        bm = None
        if best >= alpha_orig:
            bm = best_move

        tt_store(board, alpha_orig, beta, best, bm, depth)

    return (best, best_move)

def calc_move(board, max_think_time, max_depth, is_ponder):
    global to_flag
    to_flag = threading.Event()
    to_flag.clear()

    t = None
    if max_think_time:
        t = threading.Timer(max_think_time, set_to_flag, args=[to_flag])
        t.start()

    reset_stats()
    tt_inc_age()

    l(board.fen())

    # FIXME
    if board.move_count() == 1 and not is_ponder:
        l('only 1 move possible')

        for m in board.get_move_list():
            break

        return [ 0, m, 0, 0.0 ]

    result = None
    alpha = -infinite
    beta = infinite

    siblings = []
    start_ts = time.time()
    d = 1
    while d < max_depth + 1:
        cur_result = search(board, alpha, beta, d, siblings, d, False)

        diff_ts = time.time() - start_ts

        if to_flag.is_set():
            if result:
                result[3] = diff_ts
            break

        stats = get_stats()

        if cur_result[1]:
            diff_ts_ms = math.ceil(diff_ts * 1000.0)

            pv = tt_get_pv(board, cur_result[1])
            msg = 'depth %d score cp %d time %d nodes %d pv %s' % (d, cur_result[0], diff_ts_ms, stats['stats_node_count'], pv)

            if not is_ponder:
                print('info %s' % msg)
                sys.stdout.flush()

            l(msg)

        result = [cur_result[0], cur_result[1], d, diff_ts]

        if max_think_time and diff_ts > max_think_time / 2.0:
            break

        if cur_result[0] <= alpha:
            alpha = -infinite
        elif cur_result[0] >= beta:
            beta = infinite
        else:
            alpha = cur_result[0] - 50
            if alpha < -infinite:
                alpha = -infinite

            beta = cur_result[0] + 50
            if beta > infinite:
                beta = infinite

            d += 1

        #l('a: %d, b: %d' % (alpha, beta))

    if t:
        t.cancel()

    if result == None or result[1] == None:
        l('random move!')
        l(board.get_stats())

        result = [ 0, random_move(board), 0, time.time() - start_ts ]

    l('selected move: %s' % result)

    diff_ts = time.time() - start_ts

    stats = get_stats()

    avg_bco = -1
    if stats['stats_avg_bco_index_cnt']:
        avg_bco = float(stats['stats_avg_bco_index']) / stats['stats_avg_bco_index_cnt']

    if stats['stats_tt_checks'] and diff_ts > 0:
        l('nps: %f, nodes: %d, tt_hits: %f%%, avg bco index: %.2f' % (stats['stats_node_count'] / diff_ts, stats['stats_node_count'], stats['stats_tt_hits'] * 100.0 / stats['stats_tt_checks'], avg_bco))

    return result

def calc_move_wrapper(board, duration, depth, is_ponder):
    global thread_result

    try:
        thread_result = calc_move(board, duration, depth, is_ponder)

    except Exception as ex:
        l(str(ex))
        l(traceback.format_exc())

        thread_result = None

import random
def random_move(board):
    moves = board.get_move_list()

    idx = 0
    while True:
        idx = random.randint(0, len(moves) - 1)

        l('n moves: %d, chosen: %d = %s' % (len(moves), idx, moves[idx]))

        if board.is_legal(moves[idx]):
            break

    return moves[idx]

thread = None
thread_result = None

def cm_thread_start(board, duration=None, depth=999999, is_ponder=False):
    global thread
    thread = threading.Thread(target=calc_move_wrapper, args=(board,duration,depth,is_ponder,))
    thread.start()

def cm_thread_check():
    global thread
    if thread:
        thread.join(0.05)

        return thread.is_alive()

    return False

def cm_thread_stop():
    global to_flag
    if to_flag:
        set_to_flag(to_flag)

    global thread
    if not thread:
        return None

    thread.join()
    del thread
    thread = None

    global thread_result
    return thread_result
