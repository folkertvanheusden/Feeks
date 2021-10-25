import chess
import chess.polyglot
from chess.polyglot import POLYGLOT_RANDOM_ARRAY

class Board(chess.Board, object):
    def __init__(self, f=chess.STARTING_FEN, c=False):
        self._moves = []
        self._hashes = []

        super(Board, self).__init__(f)

    def _get_move_list(self):
        return list(self.generate_pseudo_legal_moves())

    def get_move_list(self):
        if not self._moves:
            self._moves.append(self._get_move_list())

        if not self._moves[-1]:
            self._moves[-1] = self._get_move_list()

        return self._moves[-1]

    def is_legal(self, m):
        if super(Board, self).is_pseudo_legal(m) == False:
            return False

        return super(Board, self).is_legal(m) 

    def move_count(self):
        return len(self.get_move_list())

    def _zh_remove_piece(self, square, hash_):
        p = self.piece_at(square)

        piece_index = (p.piece_type - 1) * 2 + int(p.color)
        array_index = 64 * piece_index + square

        return hash_ ^ POLYGLOT_RANDOM_ARRAY[array_index]

    def _zh_put_piece(self, square, p, hash_):
        piece_index = (p.piece_type - 1) * 2 + int(p.color)
        array_index = 64 * piece_index + square

        return hash_ ^ POLYGLOT_RANDOM_ARRAY[array_index]

    def _zh_swap_color(self, hash_):
        return hash_ ^ POLYGLOT_RANDOM_ARRAY[780]

    def get_zh(self):
        if len(self._hashes) == 0:
            self._hashes.append(chess.polyglot.zobrist_hash(self))

        return self._hashes[-1]

    def push(self, m):
        #print(self.fen(), m)

        me = self.piece_at(m.from_square)

        force = False
        if m == chess.Move.null():
            # no null move at root
            hash_ = self._hashes[-1] if len(self._hashes) else chess.polyglot.zobrist_hash(self)
            hash_ = self._zh_swap_color(hash_)

        elif self.is_en_passant(m) or self.is_castling(m) or me.piece_type == chess.KING or me.piece_type == chess.ROOK:
            force = True

        else:
            hash_ = self._hashes[-1] if len(self._hashes) else chess.polyglot.zobrist_hash(self)
            #print('\t\t', hash_ == None or hash_ == chess.polyglot.zobrist_hash(self))

            victim = self.piece_at(m.to_square)
            if victim:
                #print 'regular capture'
                hash_ = self._zh_remove_piece(m.to_square, hash_)
            else:
                #print 'regular move'
                pass

            hash_ = self._zh_remove_piece(m.from_square, hash_)

            hash_ = self._zh_put_piece(m.to_square, me, hash_)

            hash_ = self._zh_swap_color(hash_)

        super(Board, self).push(m)

        if force:
            hash_ = chess.polyglot.zobrist_hash(self)

        #print('\t\t', hash_ == None or hash_ == chess.polyglot.zobrist_hash(self))

        self._moves.append(None)
        self._hashes.append(hash_)

        #print(len(self._hashes), len(self._moves) == len(self._hashes))

    def pop(self):
        del self._moves[-1]
        del self._hashes[-1]

        return super(Board, self).pop()

    def _set_lists(self, lists):
        self._moves = lists

    def _clear(self):
        self._moves = []
        self._hashes = []

    def copy(self):
        c = super(Board, self).copy()
        c._clear()
        return c

    def get_stats(self):
        return { 'len' : len(self._moves) }

if __name__ == "__main__":
    sq = 8

    b = Board('rnbqkbnr/ppppp1pp/5p2/8/8/5N2/PPPPPPPP/RNBQKB1R w KQkq - 0 2')
    b.push(chess.Move.from_uci('h1g1'))
    print(b.get_zh(), chess.polyglot.zobrist_hash(b), b.get_zh() == chess.polyglot.zobrist_hash(b))

    print('---')

    b = Board()
    #b._clear()
    b.push(chess.Move.from_uci('b1c3'))
    print(b.get_zh(), chess.polyglot.zobrist_hash(b), b.get_zh() == chess.polyglot.zobrist_hash(b))
    b.push(chess.Move.from_uci('e7e5'))
    print(b.get_zh(), chess.polyglot.zobrist_hash(b), b.get_zh() == chess.polyglot.zobrist_hash(b))
    b.push(chess.Move.from_uci('d2d4'))
    print(b.get_zh(), chess.polyglot.zobrist_hash(b), b.get_zh() == chess.polyglot.zobrist_hash(b))
    b.push(chess.Move.from_uci('e5d4'))
    print(b.get_zh(), chess.polyglot.zobrist_hash(b), b.get_zh() == chess.polyglot.zobrist_hash(b))
