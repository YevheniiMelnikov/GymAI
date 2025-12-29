from enum import Enum, auto


class AutoName(str, Enum):
    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[str]) -> str:
        return name


class ButtonText(AutoName):
    female = auto()
    male = auto()

    quit = auto()
    done = auto()
    select = auto()
    prev_menu = auto()
    delete = auto()
    pay = auto()
    ask_ai = auto()
    ask_ai_again = auto()
    create_diet = auto()
    diet_again = auto()
    confirm_generate = auto()
    main_menu = auto()

    my_profile = auto()
    my_program = auto()
    balance_status = auto()
    edit = auto()
    program = auto()
    subscription = auto()
    subscription_1_month = auto()
    subscription_6_months = auto()
    subscription_12_months = auto()
    max_plan = auto()
    optimum_plan = auto()
    start_plan = auto()
    workout_goals = auto()
    workout_experience = auto()
    workout_location = auto()
    health_notes = auto()
    diet_allergies = auto()
    diet_products = auto()
    language = auto()
    weight = auto()
    height = auto()

    feedback = auto()
    send_feedback = auto()
    faq = auto()

    beginner = auto()
    intermediate = auto()
    advanced = auto()
    experienced = auto()
    gym_workout = auto()
    home_workout = auto()

    view = auto()
    weekly_survey_answer = auto()

    answer_yes = auto()
    answer_no = auto()
    enabled = auto()
    disabled = auto()
    plant_food = auto()
    meat = auto()
    fish_seafood = auto()
    eggs = auto()
    dairy = auto()

    def __str__(self) -> str:
        return f"buttons.{self.name}"


class MessageText(AutoName):
    invalid_content = auto()
    questionnaire_not_completed = auto()
    unexpected_error = auto()
    coach_agent_error = auto()

    profile_info = auto()
    default_status = auto()
    request_in_progress = auto()
    waiting_for_text = auto()
    choose_gender = auto()
    born_in = auto()
    workout_goals = auto()
    workout_location = auto()
    weight = auto()
    height = auto()
    workout_experience = auto()
    health_notes = auto()
    health_notes_question = auto()
    diet_allergies_question = auto()
    diet_allergies = auto()
    diet_products = auto()
    diet_service_intro = auto()

    edit_profile = auto()
    choose_profile_parameter = auto()
    verified = auto()
    finish_registration_to_get_credits = auto()
    finish_registration = auto()
    initial_credits_granted = auto()
    credit_balance_menu = auto()
    not_enough_credits = auto()
    subscription_type_prompt = auto()
    subscription_already_active = auto()
    confirm_service = auto()
    weekly_survey_submitted = auto()

    profile_deleted = auto()
    profile_data_not_found_error = auto()
    accept_policy = auto()
    your_data_updated = auto()
    select_language = auto()

    enter_wishes = auto()
    delete_confirmation = auto()
    split_number_selection = auto()
    weekly_survey_prompt = auto()

    payment_failure = auto()
    payment_in_progress = auto()
    contract_info_message = auto()
    follow_link = auto()
    main_menu = auto()
    help = auto()
    info = auto()
    start = auto()
    saved = auto()
    feedback = auto()
    feedback_menu = auto()
    feedback_sent = auto()
    new_feedback = auto()
    ask_ai_response_template = auto()
    diet_response_template = auto()

    ask_ai_prompt = auto()
    out_of_range = auto()
    new_workout_plan = auto()
    program_updated = auto()
    subscription_created = auto()
    not_verified = auto()

    def __str__(self) -> str:
        return f"messages.{self.name}"
