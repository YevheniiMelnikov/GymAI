from aiogram.fsm.state import State, StatesGroup


class States(StatesGroup):
    main_menu = State()
    feedback = State()
    feedback_menu = State()

    select_language = State()

    gender = State()
    born_in = State()
    workout_goals = State()
    workout_location = State()
    workouts_number = State()
    weight = State()
    height = State()
    workout_experience = State()
    health_notes_choice = State()
    health_notes = State()
    enter_wishes = State()
    accept_policy = State()

    edit_profile = State()
    profile = State()
    profile_delete = State()

    workout_survey = State()
    program_view = State()
    confirm_subscription_reset = State()
    exercise_weight = State()
    toggle_drop_set = State()
    enter_sets = State()
    enter_reps = State()
    add_exercise_name = State()

    edit_exercise = State()
    edit_exercise_parameter = State()
    program_edit = State()
    delete_exercise = State()
    show_subscription = State()
    subscription_manage = State()
    program_manage = State()
    subscription_history = State()
    program_action_choice = State()

    handle_payment = State()
    choose_plan = State()
    ask_ai_question = State()
    choose_ai_service = State()
    workout_days_selection = State()
    confirm_service = State()
    ai_confirm_service = State()
    subscription_action_choice = State()
