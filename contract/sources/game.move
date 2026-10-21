module blockword::game {
    use std::bcs;
    use std::hash;
    use std::signer;
    use std::vector;
    use aptos_std::ed25519;
    use aptos_framework::event;

    const E_AUTH: u64 = 1;
    const E_ACTIVE: u64 = 2;
    const E_FINISHED: u64 = 3;
    const E_WORD: u64 = 4;
    const E_FEEDBACK: u64 = 5;
    const E_COMMITMENT: u64 = 6;
    const E_NOT_FINISHED: u64 = 7;
    const E_REVEALED: u64 = 8;
    const E_CONFIGURED: u64 = 9;
    const E_ROUND: u64 = 10;

    struct Config has key { oracle_key: vector<u8> }
    struct Game has key, copy, drop, store {
        round_id: u64,
        commitment: vector<u8>,
        guesses: vector<vector<u8>>,
        feedback: vector<vector<u8>>,
        finished: bool,
        verified: bool,
        won: bool,
        answer: vector<u8>
    }
    struct Passport has key, copy, drop, store {
        rounds: u64, verified_rounds: u64, wins: u64, total_guesses: u64
    }
    // bind permits to this function, deployment and player so they cannot be replayed elsewhere.
    struct StartPermit has drop {
        domain: vector<u8>, deployment: address, player: address,
        round_id: u64, commitment: vector<u8>
    }
    struct GuessPermit has drop {
        domain: vector<u8>, deployment: address, player: address,
        round_id: u64, attempt: u64, guess: vector<u8>, feedback: vector<u8>
    }
    struct AnswerCommitment has drop {
        domain: vector<u8>, deployment: address, player: address,
        round_id: u64, answer: vector<u8>, salt: vector<u8>
    }
    #[event]
    struct RoundOpened has drop, store {
        player: address, round_id: u64, commitment: vector<u8>
    }
    #[event]
    struct GuessRecorded has drop, store {
        player: address, round_id: u64, attempt: u64,
        guess: vector<u8>, feedback: vector<u8>
    }
    #[event]
    struct RoundVerified has drop, store {
        player: address, round_id: u64, won: bool,
        attempts: u64, answer: vector<u8>, salt: vector<u8>
    }

    public entry fun configure(owner: &signer, oracle_key: vector<u8>) {
        assert!(signer::address_of(owner) == @blockword, E_AUTH);
        assert!(!exists<Config>(@blockword), E_CONFIGURED);
        assert!(vector::length(&oracle_key) == 32, E_AUTH);
        move_to(owner, Config { oracle_key });
    }

    fun check_signature(message: vector<u8>, signature: vector<u8>) acquires Config {
        let key = ed25519::new_unvalidated_public_key_from_bytes(
            borrow_global<Config>(@blockword).oracle_key
        );
        let sig = ed25519::new_signature_from_bytes(signature);
        assert!(ed25519::signature_verify_strict(&sig, &key, message), E_AUTH);
    }

    public entry fun start(
        player: &signer, round_id: u64, commitment: vector<u8>, signature: vector<u8>
    ) acquires Config, Game, Passport {
        let addr = signer::address_of(player);
        assert!(vector::length(&commitment) == 32, E_COMMITMENT);
        if (!exists<Passport>(addr)) {
            move_to(player, Passport { rounds: 0, verified_rounds: 0, wins: 0, total_guesses: 0 });
        };
        let passport = borrow_global_mut<Passport>(addr);
        assert!(round_id == passport.rounds + 1, E_ROUND);
        let permit = StartPermit {
            domain: b"BLOCKWORD_START_V1", deployment: @blockword,
            player: addr, round_id, commitment
        };
        check_signature(bcs::to_bytes(&permit), signature);
        if (exists<Game>(addr)) {
            assert!(borrow_global<Game>(addr).verified, E_ACTIVE);
        };
        let game = Game {
            round_id, commitment, guesses: vector[], feedback: vector[],
            finished: false, verified: false, won: false, answer: vector[]
        };
        if (exists<Game>(addr)) { *borrow_global_mut<Game>(addr) = game }
        else { move_to(player, game) };
        passport.rounds = round_id;
        event::emit(RoundOpened { player: addr, round_id, commitment });
    }

    public entry fun guess(
        player: &signer, word: vector<u8>, feedback: vector<u8>, signature: vector<u8>
    ) acquires Config, Game {
        let addr = signer::address_of(player);
        let game = borrow_global_mut<Game>(addr);
        assert!(!game.finished, E_FINISHED);
        assert!(valid_word(&word), E_WORD);
        assert!(vector::length(&feedback) == 5, E_FEEDBACK);
        let i = 0;
        while (i < 5) { assert!(*vector::borrow(&feedback, i) <= 2, E_FEEDBACK); i = i + 1; };
        let attempt = vector::length(&game.guesses) + 1;
        assert!(attempt <= 6, E_FINISHED);
        let permit = GuessPermit {
            domain: b"BLOCKWORD_GUESS_V1", deployment: @blockword,
            player: addr, round_id: game.round_id, attempt, guess: word, feedback
        };
        check_signature(bcs::to_bytes(&permit), signature);
        vector::push_back(&mut game.guesses, word);
        vector::push_back(&mut game.feedback, feedback);
        game.won = feedback == vector[2, 2, 2, 2, 2];
        game.finished = game.won || attempt == 6;
        event::emit(GuessRecorded {
            player: addr, round_id: game.round_id, attempt, guess: word, feedback
        });
    }

    public entry fun forfeit(player: &signer) acquires Game {
        let game = borrow_global_mut<Game>(signer::address_of(player));
        assert!(!game.finished, E_FINISHED);
        game.finished = true;
    }

    public entry fun reveal(player: &signer, answer: vector<u8>, salt: vector<u8>)
    acquires Game, Passport {
        let addr = signer::address_of(player);
        let game = borrow_global_mut<Game>(addr);
        assert!(game.finished, E_NOT_FINISHED);
        assert!(!game.verified, E_REVEALED);
        assert!(valid_word(&answer), E_WORD);
        assert!(vector::length(&salt) == 32, E_COMMITMENT);
        let opening = AnswerCommitment {
            domain: b"BLOCKWORD_ANSWER_V1", deployment: @blockword,
            player: addr, round_id: game.round_id, answer, salt
        };
        assert!(hash::sha3_256(bcs::to_bytes(&opening)) == game.commitment, E_COMMITMENT);
        let attempts = vector::length(&game.guesses);
        let i = 0;
        while (i < attempts) {
            assert!(score(&answer, vector::borrow(&game.guesses, i)) ==
                *vector::borrow(&game.feedback, i), E_FEEDBACK);
            i = i + 1;
        };
        game.verified = true;
        game.answer = answer;
        let passport = borrow_global_mut<Passport>(addr);
        passport.verified_rounds = passport.verified_rounds + 1;
        passport.total_guesses = passport.total_guesses + attempts;
        if (game.won) { passport.wins = passport.wins + 1; };
        event::emit(RoundVerified {
            player: addr, round_id: game.round_id, won: game.won, attempts, answer, salt
        });
    }

    // consume exact matches first, then use each remaining copy for one misplaced match.
    public fun score(answer: &vector<u8>, guess: &vector<u8>): vector<u8> {
        assert!(vector::length(answer) == 5 && vector::length(guess) == 5, E_WORD);
        let result = vector[0u8, 0, 0, 0, 0];
        let used = vector[false, false, false, false, false];
        let i = 0;
        while (i < 5) {
            if (vector::borrow(answer, i) == vector::borrow(guess, i)) {
                *vector::borrow_mut(&mut result, i) = 2;
                *vector::borrow_mut(&mut used, i) = true;
            };
            i = i + 1;
        };
        i = 0;
        while (i < 5) {
            if (*vector::borrow(&result, i) == 0) {
                let j = 0;
                while (j < 5) {
                    if (!*vector::borrow(&used, j) &&
                        vector::borrow(guess, i) == vector::borrow(answer, j)) {
                        *vector::borrow_mut(&mut result, i) = 1;
                        *vector::borrow_mut(&mut used, j) = true;
                        break
                    };
                    j = j + 1;
                };
            };
            i = i + 1;
        };
        result
    }

    public fun valid_word(word: &vector<u8>): bool {
        vector::contains(&words(), word)
    }

    #[view]
    public fun words(): vector<vector<u8>> {
        vector[b"aptos", b"asset", b"block", b"bytes", b"chain", b"coins",
            b"dapps", b"epoch", b"layer", b"miner", b"nodes", b"nonce",
            b"peers", b"proof", b"relay", b"shard", b"stake", b"state",
            b"swaps", b"token", b"trust", b"vault"]
    }

    #[view]
    public fun game_state(player: address): Game acquires Game { *borrow_global<Game>(player) }
    #[view]
    public fun passport(player: address): Passport acquires Passport { *borrow_global<Passport>(player) }

    #[test]
    fun repeated_letters() {
        assert!(score(&b"peers", &b"epoch") == vector[1, 1, 0, 0, 0], 100);
        assert!(score(&b"stake", &b"state") == vector[2, 2, 2, 0, 2], 101);
        assert!(score(&b"peers", &b"peers") == vector[2, 2, 2, 2, 2], 102);
        assert!(score(&b"aptos", &b"peers") == vector[1, 0, 0, 0, 2], 103);
    }

    #[test_only]
    fun test_salt(): vector<u8> {
        x"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"
    }

    #[test_only]
    fun test_commitment(player: address, round_id: u64): vector<u8> {
        hash::sha3_256(bcs::to_bytes(&AnswerCommitment {
            domain: b"BLOCKWORD_ANSWER_V1", deployment: @blockword,
            player, round_id, answer: b"peers", salt: test_salt()
        }))
    }

    #[test_only]
    fun test_open(owner: &signer, player: &signer): ed25519::SecretKey
    acquires Config, Game, Passport {
        let (sk, pk) = ed25519::generate_keys();
        configure(owner, ed25519::validated_public_key_to_bytes(&pk));
        let addr = signer::address_of(player);
        let commitment = test_commitment(addr, 1);
        let permit = StartPermit {
            domain: b"BLOCKWORD_START_V1", deployment: @blockword,
            player: addr, round_id: 1, commitment
        };
        let sig = ed25519::sign_arbitrary_bytes(&sk, bcs::to_bytes(&permit));
        start(player, 1, commitment, ed25519::signature_to_bytes(&sig));
        sk
    }

    #[test_only]
    fun test_guess(player: &signer, sk: &ed25519::SecretKey, word: vector<u8>, feedback: vector<u8>)
    acquires Config, Game {
        let addr = signer::address_of(player);
        let game = borrow_global<Game>(addr);
        let permit = GuessPermit {
            domain: b"BLOCKWORD_GUESS_V1", deployment: @blockword,
            player: addr, round_id: game.round_id,
            attempt: vector::length(&game.guesses) + 1, guess: word, feedback
        };
        let sig = ed25519::sign_arbitrary_bytes(sk, bcs::to_bytes(&permit));
        guess(player, word, feedback, ed25519::signature_to_bytes(&sig));
    }

    #[test(owner = @blockword, player = @0xbeef)]
    fun verified_win(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let sk = test_open(owner, player);
        test_guess(player, &sk, b"epoch", vector[1, 1, 0, 0, 0]);
        test_guess(player, &sk, b"peers", vector[2, 2, 2, 2, 2]);
        reveal(player, b"peers", test_salt());
        let p = passport(signer::address_of(player));
        assert!(p.wins == 1 && p.verified_rounds == 1 && p.total_guesses == 2, 110);
        assert!(game_state(signer::address_of(player)).verified, 111);
    }

    #[test(owner = @blockword, player = @0xbeef)]
    fun six_guesses_and_loss(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let sk = test_open(owner, player);
        let i = 0;
        while (i < 6) { test_guess(player, &sk, b"epoch", vector[1, 1, 0, 0, 0]); i = i + 1; };
        reveal(player, b"peers", test_salt());
        let p = passport(signer::address_of(player));
        assert!(p.wins == 0 && p.verified_rounds == 1 && p.total_guesses == 6, 112);
    }

    #[test(owner = @blockword, player = @0xbeef)]
    fun forfeit_has_no_win(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let _sk = test_open(owner, player);
        forfeit(player);
        reveal(player, b"peers", test_salt());
        let p = passport(signer::address_of(player));
        assert!(p.wins == 0 && p.verified_rounds == 1, 113);
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_COMMITMENT, location = Self)]
    fun changed_answer_rejected(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let _sk = test_open(owner, player);
        forfeit(player);
        reveal(player, b"aptos", test_salt());
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_FEEDBACK, location = Self)]
    fun dishonest_oracle_cannot_settle(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let sk = test_open(owner, player);
        test_guess(player, &sk, b"epoch", vector[2, 2, 2, 2, 2]);
        reveal(player, b"peers", test_salt());
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_NOT_FINISHED, location = Self)]
    fun early_reveal_rejected(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let _sk = test_open(owner, player);
        reveal(player, b"peers", test_salt());
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_REVEALED, location = Self)]
    fun duplicate_settlement_rejected(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let _sk = test_open(owner, player);
        forfeit(player);
        reveal(player, b"peers", test_salt());
        reveal(player, b"peers", test_salt());
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_FINISHED, location = Self)]
    fun seventh_guess_rejected(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let sk = test_open(owner, player);
        let i = 0;
        while (i < 7) { test_guess(player, &sk, b"epoch", vector[1, 1, 0, 0, 0]); i = i + 1; };
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_AUTH, location = Self)]
    fun forged_feedback_rejected(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let _sk = test_open(owner, player);
        let (attacker, _pk) = ed25519::generate_keys();
        test_guess(player, &attacker, b"peers", vector[2, 2, 2, 2, 2]);
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_WORD, location = Self)]
    fun unknown_word_rejected(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let sk = test_open(owner, player);
        test_guess(player, &sk, b"hello", vector[0, 0, 0, 0, 0]);
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_AUTH, location = Self)]
    fun signature_replay_rejected(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let sk = test_open(owner, player);
        let permit = GuessPermit {
            domain: b"BLOCKWORD_GUESS_V1", deployment: @blockword,
            player: signer::address_of(player), round_id: 1, attempt: 1,
            guess: b"epoch", feedback: vector[1, 1, 0, 0, 0]
        };
        let sig = ed25519::signature_to_bytes(&ed25519::sign_arbitrary_bytes(&sk, bcs::to_bytes(&permit)));
        guess(player, b"epoch", vector[1, 1, 0, 0, 0], sig);
        guess(player, b"epoch", vector[1, 1, 0, 0, 0], sig);
    }

    #[test(owner = @blockword, player = @0xbeef)]
    #[expected_failure(abort_code = E_ACTIVE, location = Self)]
    fun active_round_cannot_be_replaced(owner: &signer, player: &signer) acquires Config, Game, Passport {
        let sk = test_open(owner, player);
        let addr = signer::address_of(player);
        let digest = test_commitment(addr, 2);
        let permit = StartPermit {
            domain: b"BLOCKWORD_START_V1", deployment: @blockword,
            player: addr, round_id: 2, commitment: digest
        };
        let sig = ed25519::signature_to_bytes(&ed25519::sign_arbitrary_bytes(&sk, bcs::to_bytes(&permit)));
        start(player, 2, digest, sig);
    }
}
