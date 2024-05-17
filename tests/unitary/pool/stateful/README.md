# Stateful testing guidelines

Welcome to the most important and fragile section of the tests. Stateful testing mixes and matches a set of allowed actions (rules) to generate every possible scenario and make sure that Curve pools always work under a set of conditions (invariants). To do so we leveraged the [hyptohesis testing framework](https://hypothesis.readthedocs.io/en/latest/index.html#) which provides stateful testing out of the box.

### Tests structure
All stateful tests are based off `StatefulBase` which contains a wrapped version of every function you might want to call from a Curve pool. Most of the fixtures that are used in the other tests have been converted into `SearchStrategies` in the `strategies.py` file. Keep in mind that titanoboa offers some EVM specific `SearchStrategies` out of the box.

### Get the most out of stateful testing

#### How to debug a stateful tests
Stateful tests can run for amounts of time (sometime even more than 30 minutes). Since we can't wait half an hour for a test to pass these tests are filled with "notes" that can help figure out what is going on. To see these notes you need to run pytest with this command:
```bash
python -m pytest --hypothesis-show-statistics --hypothesis-verbosity=verbose -s path/to/test.py
```

`--hypothesis-show-statistics` while not being necessary for showing notes, can be helpful to have some statistics of what happens in the test.

---
If you see a test reverting but not stopping it's because it is in the shrinking phase! Sometime shrinking can take a lot of time without leading to significant results. If you want to skip the shrinking phase and get straight to the error you can do so by enabling the `no-shrink` profile defined in `strategies.py`. It sufficies to add this line to your test:
```python
settings.load_profile("no-shrink")
```


#### Before writing/updating stateful tests
Read the docs multiple times through your stateful testing journey. Not only the stateful testing section but the whole hypothesis docs. Stateful testing might look like an isolated part of hypothesis, but the reality is that it is built on top of `SearchStrategies` and requires a very deep understanding of how hypothesis works. If you are wondering why one hypothesis functionality is useful, you're probably not capable of writing good tests (yet).

#### What you should do with stateful testing
- Build these tests with composability in mind, by inheriting a test class you can test for more specific situations in which the pool might be (invariant stateful tests are a good example of this).
- It's better to build "actions" as methods (like the ones in `StatefulBase`), and then turn them into rules later by inheriting in a subclass. This helps for maintainability and code reusability.

#### What you should **not** do with stateful testing
- Do not use stateful testing to reliably test for edge cases in considerations, if a function is known to revert under a certain input you should make sure your `SearchStrategy` never generates that input in the first place. For this very reason you should try to avoid using `try/excpet` and returning when a function hits an edge case. The test doesn't pass? Restrict your `SearchStrategy` and don't create early termination conditions.
- Do not try to use `pytest` fixtures in stateful tests. While we have done this in the past, for this to work we need to use `run_state_machine_as_test` which breaks a lot of the features that make stateful testing so powerful (i.e. test statistics). To achieve the same result you should convert the fixture into an hypothesis native `SearchStrategy`. Keep in mind that a lot of strategies have been already built
- Do not replicate good actors behavior in rules

#### Practical suggestions
- `Bundles` are a nice feature but they are often too limited in practice, you can easily build a more advanced bundle-like infrastructure with lists. (The way depositors are tracked in the tests is a good example of how you can build something more flexible than a bundle).
- Everything you can do with `.flatmap` can be achieved with the `@composite` decorator. While it's fun to do some functional programming (no pun intended), strategies built with `@composite` are a LOT more readable.
