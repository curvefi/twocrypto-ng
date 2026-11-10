from hypothesis import Phase, settings

settings.register_profile("no-shrink", settings(phases=list(Phase)[:4]))
