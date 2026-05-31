from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional


class ClaimForm(FlaskForm):
    lost_item_id = SelectField("Related lost report", coerce=int, validators=[Optional()])
    proof_text = TextAreaField(
        "Ownership proof",
        validators=[DataRequired(), Length(min=20, max=3000)],
    )
    supporting_image = FileField(
        "Supporting image",
        validators=[FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only.")],
    )
    submit = SubmitField("Submit claim")
